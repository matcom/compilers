---
student: Ronald Provance Valladares, Agustin A. Carbajal Romero, Dylan R. Cabrera Morales (C312)
issue: 27
repo: agustin030902/Hulk-Compiler
branch: main
date: 2026-07-02
---

# Evaluación Automática — Hulk-Compiler (Ronald Provance, Agustin Carbajal, Dylan Cabrera)

- **Repositorio**: https://github.com/agustin030902/Hulk-Compiler
- **Rama**: `main`
- **Fecha de evaluación**: 2026-07-02
- **Issue del curso**: [#27](https://github.com/matcom/compilers/issues/27)
- **Última corrida de CI verificada**: 2026-06-23 (71/71 requeridos + 10/10 extras)

---

## 1. Arquitectura del compilador

Hulk-Compiler es un compilador de HULK escrito en **Rust edition 2024** que sigue un pipeline clásico de cuatro etapas —léxico, sintáctico, semántico y generación de código— con módulos independientes y una orquestación centralizada en `src/compiler/mod.rs` (237 LOC). El binario principal `Hulk-Compiler` (`src/main.rs`, 96 LOC) lee un archivo `.hulk` desde `argv[1]`, invoca el pipeline, escribe el IR intermedio en `temp.ll` y delega la compilación final a `clang -Wno-override-module temp.ll -lm -o output`. El programa completo (sin GUI ni tests) suma alrededor de **6 700 LOC** de Rust propio, distribuidas de forma equilibrada entre lexer (394 LOC), parser (214 LOC en `mod.rs` + 406 LOC de definición de AST en `expression.rs` + 985 LOC de gramática LALRPOP en `grammar.lalrpop`), análisis semántico (840 LOC de `symbol_collector.rs` y 874 LOC del `type_checker`) y codegen LLVM (~2 700 LOC repartidas en el árbol `codegen/llvm/backend/emit/`).

**Dependencias externas.** El manifiesto (`Cargo.toml`) declara tres crates:

- `logos = "0.14"` — generador declarativo de lexer (DFA compilado en tiempo de build).
- `lalrpop-util = "0.22"` con la herramienta `lalrpop = "0.22"` como build-dependency — generador de parser LR(1).
- `eframe = "0.33"` (con `default-features = true`) — framework GUI inmediato basado en `egui`.

Esta combinación es una de las decisiones distintivas de esta entrega: el proyecto incluye **un segundo binario `gui.rs`** (`src/bin/gui.rs`, 1 412 LOC) que expone una interfaz gráfica interactiva construida con `egui/eframe`. La GUI permite editar programas HULK, visualizar tokens, AST y errores en paneles diferenciados, y ejecutar el pipeline de compilación desde el propio editor. No es funcionalidad exigida por la rúbrica, pero denota inversión adicional de trabajo del equipo.

**Decisión arquitectónica distintiva: LLVM IR emitido como texto.** A diferencia de otras entregas del cohort que usan `inkwell` (bindings de LLVM), Hulk-Compiler **construye el IR carácter a carácter como `String`** dentro del `LlvmBackend` (`src/codegen/llvm/backend/mod.rs:18-39`). La estructura mantiene tres buffers separados —`body_lines`, `function_lines`, `global_lines`— que se ensamblan al final en un módulo LLVM. El propio `REPORT.md` §6.2 justifica esta elección por dos razones: evita el problema de matching de versiones de LLVM y simplifica la depuración (el desarrollador puede leer el IR generado). El costo asumido es la pérdida de validación de tipos en tiempo de compilación: los errores se detectan solo cuando `clang` rechaza el texto emitido.

**Contrato con el corredor de tests.** `main.rs:44-58` mapea la primera categoría de error del reporte a un exit code (léxico=1, sintáctico=2, semántico=3), respetando el contrato esperado por el runner del curso. Si el codegen falla, se emite exit 3 con `SEMANTIC: LLVM compilation failed`. El diseño es **fail-fast por fase**: `compile()` en `src/compiler/mod.rs:60-117` corre lexer → parser → semántica → codegen deteniéndose apenas una fase produce errores, y devuelve un `CompileReport` con la lista completa de diagnósticos.

## 2. Análisis léxico

`src/lexer/mod.rs` (394 LOC) implementa el lexer sobre `logos = "0.14"`. Se define un `enum LogosTokenKind` con derivaciones de macro `#[derive(Logos, …)]` (líneas 12-133) que declara **57 tokens**: palabras clave (`let`, `function`, `type`, `protocol`, `extends`, `new`, `while`, `for`, `range`, `if`/`elif`/`else`, `print`, `PI`, `E`, `sin`, `cos`, `sqrt`, `exp`, `log`, `rand`, `in`, `null`, `inherits`, `is`, `as`), operadores (`+`, `^`, `@`, `@@`, `-`, `*`, `/`, `%`, `==`, `!=`, `<=`, `>=`, `<`, `>`, `&&`, `||`, `!`, `:=`, `=`, `=>`), delimitadores (`(`, `)`, `.`, `{`, `}`, `,`, `;`, `:`), y literales (`Boolean`, `Number`, `String`, `Identifier`). Todas las palabras clave llevan `priority = 3` para dominar sobre el patrón de identificador (líneas 15-66).

**Recuperación de errores.** El bucle principal (`Lexer::lex`, líneas 243-348) no aborta al primer error: cuando `logos` produce `Err(_)`, se agrega un `CompilerError::new(ErrorCategory::Lexical, …)` con posición precisa y se emite un token `TokenKind::Unknown` para que el parser tenga un token de continuidad. También se maneja explícitamente `InvalidNumberIdent` —un patrón separado con `priority = 2` y regex `[0-9]+[A-Za-z_][A-Za-z0-9_]*` (líneas 69-70)— para detectar identificadores que comienzan con dígito.

**Procesamiento de strings y escapes.** El lexer reconoce strings con la regex `r#""([^"\\]|\\.)*"#` (línea 75) y ejecuta `unescape_string_contents` (líneas 370-394) para expandir las secuencias `\"`, `\n`, `\t`; un escape inválido se reporta como error léxico. El unescape se hace **en el lexer** para que el parser reciba strings ya materializadas.

**Tracking de posición.** La función auxiliar `advance_position` (líneas 359-368) recorre los bytes del input entre los offsets del span de `logos` para actualizar línea y columna. Cada `Token` almacena `line`, `column`, `start`, `end`, lo que permite mensajes de error precisos en fases posteriores.

Observación de calidad: no hay soporte para comentarios (`//` o `/* */`). Los espacios en blanco se descartan vía el atributo `#[logos(skip r"[ \t\r\n\f]+")]` (línea 13). Esto es consistente con la sintaxis mínima documentada de HULK.

## 3. Análisis sintáctico

El parser se genera con **LALRPOP 0.22** a partir de `src/parser/grammar.lalrpop` (985 LOC). El `build.rs` invoca `lalrpop::process_root()` para compilar la gramática en tiempo de build a un `parser/grammar.rs`. La interfaz externa (`src/parser/mod.rs`) es fina: `Parser::parse_program` (líneas 34-49) convierte los tokens en un iterador `(usize, TokenKind, usize)` que LALRPOP consume, y traduce cada `lalrpop_util::ParseError` variant a un `CompilerError` con línea/columna resueltas por `offset_to_line_column`.

**Estructura de la gramática (`grammar.lalrpop`).** El símbolo raíz `Program` (líneas 80-99) impone la separación entre declaraciones y sentencias que habilita el hoisting completo:

```
Program := Declaration* Statements "eof"
Declaration := InterfaceDecl | TypeDecl | FunctionDecl
```

Las declaraciones se recolectan en listas separadas (`types`, `interfaces`, `functions`) dentro del AST (`Program` en `src/parser/expression.rs:14-19`), y las sentencias van a `statements`. Esto significa que el análisis semántico puede procesar todo el vocabulario global antes de mirar los cuerpos, sin requerir un paso de reordenamiento.

**Precedencia estratificada de expresiones.** La gramática divide toda expresión en dos cadenas paralelas —lo que `REPORT.md` §4.3 llama "cadena cerrada" y "cadena abierta"— para permitir que estructuras de control (`if`, `while`, `for`, `let-in`) aparezcan como operandos derechos de operadores binarios sin necesidad de paréntesis. La cadena cerrada (`BaseExpr → Assignment → LogicalOr → … → Primary`, líneas 366-615) es la típica pirámide LR de precedencia; la cadena abierta (`ExtExpr → OrTail → AndTail → … → FlowAtom`, líneas 617-757) reutiliza el operando izquierdo de la cadena cerrada pero termina en `FlowAtom = IfExpr | WhileExpr | ForExpr | LetIn` (línea 374). Esta duplicación de reglas es la maquinaria que permite `5 + if (c) 3 else 10` o `x + let a = 1 in a`.

**Elementos del lenguaje reconocidos.** `TypeDecl` (líneas 158-194) admite parámetros de constructor y `inherits Parent(args)` con expresiones de inicialización. `InterfaceDecl` (líneas 107-143) soporta `extends`. `FunctionDecl` (líneas 257-280) y `TypeMember` (métodos, líneas 233-254) aceptan ambos cuerpos con `=>` o `{ … }`. Se distinguen los operadores `=` (asignación regular) y `:=` (asignación destructiva); el segundo acepta `Expr` completa como lado derecho, no solo cadena cerrada (líneas 430-457). El operador `range(min, max)` se desugars en el propio parser a `Expr::New(NewExpr { type_name: "Range", … })` (líneas 901-907), integrando el built-in `Range` al sistema de tipos como si fuera un `type` de usuario.

**Diagnósticos.** `parse_error_to_compiler` (líneas 60-106) traduce cada variant de `ParseError` (`InvalidToken`, `UnrecognizedEof`, `UnrecognizedToken`, `ExtraToken`, `User`) a mensajes con lista de tokens esperados y label para el token encontrado (`token_label`, líneas 116-179). Los mensajes son informativos, no crípticos.

**Ausencia de features no marcados.** Coherente con lo declarado en el issue #27, la gramática **no tiene producciones** para arrays (no hay tokens `[`/`]` en el lexer ni reglas asociadas), lambdas (no hay `\(...) => body` ni `fn` anónimo), ni macros. La búsqueda de `Bracket`, `Array`, `Vector`, `Lambda` en `src/lexer/token.rs` y `grammar.lalrpop` no arroja resultados. Esto explica los tres bloques de tests bonus fallidos.

## 4. Análisis semántico

El análisis semántico se organiza en **dos pasadas explícitas** (`src/semantic/analyzer.rs:87-110`):

1. **`SignatureInferencePass::infer_function_signatures`** — un pre-pase de inferencia iterativa (`src/semantic/pipeline/signature_inference_pass.rs`, 166 LOC) con límite `MAX_INFERENCE_PASSES = 8` (línea 11). Se ejecuta antes de la recolección propiamente dicha para propagar información entre funciones mutuamente recursivas.
2. **`SymbolCollector`** — recolección de símbolos (`src/semantic/pipeline/symbol_collector.rs`, 840 LOC). Registra tipos (`collect_types`), interfaces (`collect_interfaces`), funciones globales (`collect_functions`), métodos de tipos (`collect_methods`) e interfaces (`collect_interface_methods`). Antes de cualquier recolección invoca `inject_splat_interfaces` que escanea el programa completo en busca de anotaciones `T*` y sintetiza una interfaz `Iterable_T` por cada tipo base encontrado (`src/semantic/pipeline/symbol_collector.rs:601-664`), con el método `current(): T` refinando el retorno de `Iterable::current(): Object`.
3. **`TypeChecker`** — verificación por-expresión (`src/semantic/pipeline/type_checker/mod.rs`, 874 LOC, más un módulo por variante de expresión: `binary_expr_checker.rs`, `for_expr_checker.rs`, `interface_checker.rs`, etc.).

**Tabla de tipos y builtins.** `TypeTable` (`src/semantic/helper/types_namespace/type_table.rs`, 183 LOC) inicializa siete tipos predefinidos con IDs consecutivos: `Number`, `Boolean`, `String`, `Unit`, `Null`, `Unknown`, `Object`. Sobre esa base se registran tres tipos adicionales: `Iterable` e `Enumerable` como interfaces (`is_interface: true`) y `Range` como struct que hereda de `Object`. `SemanticAnalyzer::reset_analysis_state` (`src/semantic/analyzer.rs:112-131`) llama a `builtins::register_builtin_iterable`, `register_builtin_range` y `register_builtin_enumerable` para poblar los métodos de estos tipos: `Iterable` recibe `next(): Boolean` y `current(): Object`; `Enumerable` recibe `iter(): Iterable`; `Range` recibe `next(): Boolean` y `current(): Number`. Además, `builtins::build_range_type_decl` (`src/semantic/builtins.rs:239-340`) construye programáticamente el `TypeDecl` de `Range` (con `min`, `max`, `current` como campos y bodies reales para `next()` y `current()`) — el tipo es "built-in" a nivel semántico pero funciona como un `TypeDecl` cualquiera en las fases posteriores.

**Recolección de tipos.** `SymbolCollector::collect_types` (`src/semantic/pipeline/symbol_collector.rs:18-...`) detecta redeclaración, colisión con nombres reservados y **ciclos de herencia** (comprobando si el padre eventualmente vuelve al hijo). Los métodos se registran con clave `type#<TypeId>::<method_name>` (`method_symbol_key`, línea 14), lo que facilita la búsqueda por receptor en el resto del pipeline.

**Verificación del bucle `for`: dualidad `Iterable`/`Enumerable`.** La pieza más interesante del análisis semántico es `for_expr_checker.rs` (222 LOC). El algoritmo (`resolve_iterable_element_type`, líneas 23-56) usa **cascada de dos protocolos**:

1. Primero intenta `try_iterable` (líneas 58-105): busca `current()` en la jerarquía de métodos del tipo del iterando. Si existe, exige que tome cero parámetros y devuelve su tipo como el tipo del elemento. Luego verifica que `next()` también exista, sea de aridad cero y retorne `Boolean`. Emite mensajes específicos ("Type X implements 'current()' but is missing 'next(): Boolean'", "wrong signature (expected '(): Boolean')").
2. Si no encuentra `current()` directo, prueba `try_enumerable` (líneas 107-194): busca `iter()`, exige que retorne un `Struct`, y sobre ese struct devuelto vuelve a verificar `next()` y `current()`. El tipo del elemento es el retorno de `current()` **del iterador retornado por `iter()`**.
3. Si ambos fallan, emite "Type X is not iterable or enumerable".

La búsqueda de métodos usa `lookup_method_in_hierarchy` (líneas 196-214), que recorre la cadena `parent` del `TypeTable` para encontrar métodos heredados. Esto permite que la interfaz auto-generada `Iterable_Number` (que hereda de `Iterable`) funcione sin redeclarar `next()`.

**Sistema de varianza en interfaces.** `interface_checker.rs` (`src/semantic/pipeline/type_checker/interface_checker.rs`, 427 LOC) implementa **covarianza en retorno + contravarianza en parámetros** para la verificación estructural. `variance_compatible` (líneas 326-365) invierte el orden (impl/interface) según si el chequeo es de parámetros (`contravariant = true`) o de retorno (`contravariant = false`) y luego decide subtipado con `is_subtype` (recorrido de la cadena `parent`). La función `validate_interface_method_call` (líneas 108-220) es la que se dispara en runtime del análisis: para cada llamada a método sobre una interfaz, verifica arity + varianza de cada parámetro + varianza del retorno, con mensajes específicos ("argument #N has incompatible variance", "return type is incompatible (covariant)"). También implementa `check_interface_variance` para chequear que una interfaz que hereda de otra respete varianza en el override.

**Inferencia de tipos.** El pre-pase `SignatureInferencePass::infer_function_signatures` corre el `TypeChecker` completo hasta 8 veces con `suppress_errors = true` para propagar información entre funciones mutuamente recursivas antes del chequeo definitivo. Es un enfoque de punto-fijo simple pero efectivo para el tamaño de programas del curso, aunque el `REPORT.md` §5.5 lo reconoce como una limitación frente a Hindley-Milner.

**Manejo de scopes.** `ScopeStack<SemanticType>` en el `SemanticAnalyzer` con `push_scope`/`pop_scope` y `assign_in_scope` para la asignación destructiva. Las variables se fijan en su declaración (`let x = 5` → `x: Number`) y ni `=` ni `:=` pueden cambiar el tipo (comprobado por `types_compatible` antes de asignar).

## 5. Sistema de tipos

El sistema de tipos combina cinco tipos primitivos (`Number`, `Boolean`, `String`, `Unit`, `Null`) más `Function`, `Struct`, y `Unknown` (`src/semantic/helper/types_namespace/types.rs:3-13`). `Object` es el padre implícito de todos los tipos declarados por el usuario y de `Range`. `Null` es asignable a "tipos referencia" —`String`, `Function`, `Struct`— pero **no** a `Number`, `Boolean` ni `Unit`, controlado por `SemanticType::is_nullable` (líneas 75-83).

**Dualidad `Iterable`/`Enumerable`.** El sistema modela dos protocolos separados para iteración: un `Iterable` **es** su propio iterador (tiene `next()`/`current()` directos, ejemplo canónico `Range`); un `Enumerable` **crea** iteradores independientes vía `iter(): Iterable` (ejemplo `MultiRange` en `examples/enumerable_vs_iterable.hulk`). Es una separación análoga a la de Rust (`Iterator` vs `IntoIterator`), Java (`Collection` vs `Iterable`) y Python (`__next__` vs `__iter__`). El impacto práctico: dos `for` sobre el mismo `Range` reutilizarían el iterador agotado —el segundo no iteraría—, mientras que dos `for` sobre un `MultiRange` obtienen iteradores frescos.

**Hoisting.** Se soporta a nivel global: cualquier `type`, `protocol` o `function` puede declararse en cualquier orden. La gramática (`Program := Declaration* Statements`) los separa; el `SymbolCollector` los registra todos antes de verificar bodies; y el `SignatureInferencePass` con 8 iteraciones propaga tipos inferidos entre definiciones mutuamente recursivas.

**Splat notation (`T*`).** No es azúcar sintáctico: durante `inject_splat_interfaces` el compilador genera una interfaz `Iterable_T` por cada tipo base `T` que aparezca en anotaciones `T*`. Esa interfaz hereda de `Iterable` y **refina** `current(): T` (en vez del `current(): Object` del padre). El resultado: `function sum(nums: Number*): Number` recibe un parámetro tipado como `Iterable_Number`, donde el compilador sabe que cada elemento es `Number` y `total + x` type-checkea. Es una forma limitada de generics —una interfaz por cada `T` distinto— pero cubre el caso real de iterar sobre colecciones homogéneas sin introducir variables de tipo, unificación ni monomorfización propia.

**Operadores `is` y `as`.** Se implementan en el análisis semántico como parseos de `Equality/AsExpr` (`grammar.lalrpop:483-513`) que producen `Expr::Is(IsExpr)` y `Expr::As(AsExpr)`. En el checker se resuelve el `TypeId` del tipo consultado y se valida contra la jerarquía. La operación semántica es siempre sobre tipos concretos; la validación de "el tipo consultado existe" y "el resultado tiene el tipo esperado" ocurre estáticamente.

## 6. Backend / Codegen

El backend LLVM está organizado en cuatro subsistemas (`src/codegen/llvm/backend/`):

- `mod.rs` (393 LOC) — estado global (`LlvmBackend`), scopes, gestión de temporales/labels/strings, subtipado, layout de la jerarquía de tipos.
- `emit/` — un archivo por variante de expresión y sentencia (20 archivos, ~2 700 LOC agregadas).
- `functions.rs`, `layout.rs`, `type_lowering.rs` — utilidades de firma, layout y traducción de tipos semánticos a `ValueType` (LLVM).

**Modelo de emisión.** El backend mantiene tres buffers de líneas de texto —`body_lines`, `function_lines`, `global_lines` (`mod.rs:19-22`)— y los concatena en `compose_module` cuando termina. Cada expresión emite instrucciones de LLVM IR como formato de string (`format!("{ptr_name} = alloca {llvm_ty}")`, `emit_body`), con contadores separados para temporales (`%t0`, `%t1`, …), labels y strings globales. Es un enfoque simple y auditable pero **sin validación de tipos LLVM en tiempo de compilación** del compilador de HULK.

**Layout de objetos.** Cada objeto es un bloque contiguo alocado con `malloc` con la forma `[type_id (i64)] [campos_del_padre…] [campos_propios…]`. El primer campo, el `type_id`, es la etiqueta de tipo usada para dispatch dinámico e `is`/`as`. Los offsets se calculan recursivamente respetando alineación natural. La consecuencia es que **un `Point3D*` puede tratarse como `Point*`** sin ajuste de puntero (los campos del padre están al inicio) — una propiedad esencial para el subtipado y coherente con la limitación a herencia simple.

**Dispatch dinámico por cascada.** Cuando se llama a un método a través de una interfaz, `emit_interface_method_dispatch` (`src/codegen/llvm/backend/emit/expr/call.rs:342-...`) genera:

1. Carga del `type_id` del receptor (`bitcast i8* to i64*`, `load i64`).
2. Cascada de comparaciones `icmp eq i64 %type_id_val, %concrete_tid` seguidas de `br i1` a un bloque `dispatch.call.N` que invoca directamente el método concreto.
3. Un bloque `dispatch.default` que llama al stub de la interfaz (si ninguna de las variantes concretas emparejó).
4. Un `phi` en `dispatch.done` que unifica los valores retornados por cada rama.

Es dispatch **O(n)** en el número de tipos concretos que implementan la interfaz, lo que el propio reporte reconoce como limitación (§6.4). La ventaja es la simplicidad: no se generan vtables ni se necesita ajuste de puntero para herencia múltiple (que no existe en HULK). Para los programas del curso, con decenas de tipos como mucho, el costo es despreciable.

**Subtipado en runtime.** El backend emite dos artefactos globales para soportar `is` y `as` (`mod.rs:308-374`):

1. Un arreglo global `@hulk_type_parents = internal global [N x i64] [i64 p0, i64 p1, …]` que mapea cada TypeId a su padre (o `-1` para tipos raíz).
2. Una función `define i1 @hulk_is_subtype(i64 %child, i64 %parent)` que recorre iterativamente la cadena de padres hasta encontrar coincidencia o `-1`. La lógica es un bucle `walk → check` con `phi` para el cursor, emitido íntegramente como LLVM IR text.

`emit_is_expr` (`src/codegen/llvm/backend/emit/expr/is_expr.rs`) compila `expr is Tipo` a: caso especial `Null` → `icmp eq i8* null, null` = `true`; caso `Struct(actual)` con `actual == target` → `icmp eq i64 tid, tid` (constant folding trivial); caso general → `call i1 @hulk_is_subtype(i64 %tag, i64 target_tid)`.

**Bucle `for`: desugar en codegen.** `emit_for_expr` (`src/codegen/llvm/backend/emit/expr/for_expr.rs`, 146 LOC) no traduce a LLVM IR directamente: **reconstruye el AST** en Rust, transformándolo en un `LetIn` con el nombre reservado `__hulk_iter__`, un `WhileExpr` con `iter.next()` como condición, y otro `LetIn` interno con `x = iter.current()` en el body. Antes de reconstruir, `has_iter_method` (líneas 92-98) consulta el tipo del iterando: si tiene `iter()`, envuelve el iterando en una llamada a `iter()`; si no, usa el iterando directamente. Es el mismo pattern que el análisis semántico usa para decidir entre `Iterable` y `Enumerable`, replicado en codegen.

Este diseño —desugar tardío— es una decisión deliberada del equipo, documentada en `REPORT.md` §4.5 y §6.5: hacer el desugar en el parser habría impedido distinguir `Iterable` de `Enumerable` (el parser no tiene información de tipos); moverlo a codegen habilita la decisión basada en tipos ya inferidos. El nombre `__hulk_iter__` con doble guión bajo se elige porque el lexer rechaza identificadores que empiezan con `_` — no puede haber colisión con variables del usuario.

**Números unificados a `double`.** El backend traduce todo número (entero o flotante) a `double` (f64) en LLVM. Es una simplificación pragmática que evita generar conversiones y sobrecarga, a costa de precisión para enteros grandes (>2^53) y de rendimiento en aritmética entera (fadd en vez de add). El sistema de tipos semántico sí distingue enteros de flotantes (`Literal::Integer` vs `Literal::Float` en `expression.rs`), pero al bajar a LLVM se colapsan.

**Built-ins.** `emit_builtin_call` (`call.rs:7-...`) traduce `sin/cos/sqrt/exp` a llamadas directas a las funciones libc (`call double @sin(…)`), `log(base, val)` a dos `call @log` + `fdiv` (calcula log en base b como `ln(v)/ln(b)`), `rand()` a `call i32 @rand()` seguido de `sitofp` y normalización dividiendo por `2147483647.0`. `print` usa `printf` con formato `%g` para números, `%s` para strings, `%d` para booleanos.

**Enlace final.** `main.rs:76-93` invoca `clang -Wno-override-module temp.ll -lm -o output`. La flag `-lm` es esencial porque el IR emitido referencia funciones de `libm` (`sin`, `cos`, `log`, `exp`, `sqrt`). El backend produce IR compatible con la versión de LLVM que trae `clang`, sin requerir una versión específica.

## 7. Features implementadas

Verificación de las categorías declaradas en el issue #27 con la corrida de CI del 2026-06-23:

| Categoría         | Marcada en issue | CI (2026-06-23) | Verificado en código |
|-------------------|:----------------:|:---------------:|----------------------|
| `minimal`         | Sí               | 20/20           | Lexer + parser + semantic + codegen básicos operativos |
| `types`           | Sí               | 10/10           | `TypeDecl` con parámetros, atributos, métodos, herencia simple; codegen con layout etiquetado |
| `oop`             | Sí               | 10/10           | Dispatch cascada, `base()`, herencia con offsets, `self` en métodos |
| `iterables`       | Sí               | (incluido en extras) | `Iterable` + `Enumerable` builtin + splat `T*` sintetizando `Iterable_T` |
| `protocols`       | Sí               | (incluido en extras) | `InterfaceDecl` estructural con varianza (covariante en retorno, contravariante en parámetros) |
| `errors/lexical`  | —                | 6/6             | Recuperación con `Unknown`, `InvalidNumberIdent`, escape inválido en strings |
| `errors/syntactic`| —                | 10/10           | Mensajes con lista de tokens esperados |
| `errors/semantic` | —                | 15/15           | Redeclaración, tipos incompatibles, conformancia de interfaz, cierre de scope |
| `extras`          | —                | 10/10           | Categoría de casos avanzados combinados |
| `vectors`/`arrays`| No               | —               | No implementado (sin `[`/`]` en lexer) |
| `functors`/`lambdas` | No            | —               | No implementado (sin producción `\(...) => …`) |
| `macros`          | No               | —               | No implementado (sin token macro) |

**Total: 71/71 tests requeridos + 10/10 extras.** Cumple el techo evaluativo del curso.

**Features distintivos verificados en código.**

- **GUI con eframe** (`src/bin/gui.rs`, 1 412 LOC). Editor con syntax highlighting via `TextEdit` y `LayoutJob`, colores Catppuccin (constantes `VS_BG_MAIN`, `VS_ACCENT`, etc. en las primeras 100 líneas), tres modos de tema comentados (VSCode, Cyberpunk, Capuccino activo), panel colapsable para AST con dos vistas (`AstViewMode::Tree` y `AstViewMode::DebugText`). Es funcionalidad **fuera del corredor de tests** pero visible como valor adicional.
- **Dualidad de protocolos de iteración**: `Iterable` (self-iterator) y `Enumerable` (crea iteradores separados). Verificado en `for_expr_checker.rs:39-45` con las funciones `try_iterable` y `try_enumerable` corriendo en cascada.
- **Splat notation con síntesis de interfaces refinadas**: `inject_splat_interfaces` sintetiza `Iterable_T extends Iterable` con `current(): T` por cada tipo `T` que aparece en anotaciones `T*` (`symbol_collector.rs:601-664`).
- **Varianza estructural en interfaces**: covariante en retorno + contravariante en parámetros (`interface_checker.rs:326-365`).

## 8. Discrepancias entre REPORT.md y código

`REPORT.md` (945 líneas, ~11 400 palabras) es notablemente extenso y detallado. La calibración con el código es alta; las discrepancias que se encuentran son menores:

1. **§6.4 "Una limitación importante"** — el reporte declara un bug conocido: "si `DogWalker` extiende `WalkerBase`, y alguien llama a `walk()` a través de la interfaz en un `DogWalker` concreto, la cascada busca el método en `DogWalker`. Pero si `DogWalker` no implementa `walk()` (lo hereda de `WalkerBase`), la cascada no encontrará el método y llamará al stub de la interfaz". El código en `emit_interface_method_dispatch` (`call.rs:342-...`) efectivamente construye `concrete_impls` filtrando por `self.method_dispatch.get(&(*tid, call.method_name.clone()))` (línea 364), y la búsqueda de métodos concretos con `lookup_method_key` (semántico, `for_expr_checker.rs:196-214`) **sí** recorre la cadena de herencia. Pero en codegen la búsqueda es más superficial: solo mira `method_dispatch`, un `HashMap<(u32, String), String>` poblado por `emit_type_decl` sin propagación al padre. Esta declaración honesta de bug conocido es un plus del reporte —trazabilidad de decisiones/limitaciones— pero no se refleja aún en fallos de tests, probablemente porque el corredor de tests del curso no incluye este caso específico.

2. **§6.7 "Números unificados como f64"**: el reporte afirma que "el sistema de tipos semántico distingue entre literales enteros y flotantes, pero al bajar a LLVM se unifican". Verificado: `Literal::Integer(i64)` y `Literal::Float(f64)` son variantes distintas en `expression.rs`, pero `emit_literal` en `codegen/llvm/backend/emit/expr/literal.rs` (52 LOC) emite ambas como `double`.

3. **§7.6.1 "print y booleanos"**: el reporte dice "Booleanos: `%d` (0/1). Los booleanos se imprimen como enteros 0 o 1, no como 'true'/'false'. Aunque se definieron constantes `@.bool.true` y `@.bool.false` en el IR, actualmente no se usan en la impresión". Esta admisión explícita de código muerto (constantes definidas pero no usadas) es coherente con lo observado en el codegen y demuestra rigor en el análisis. No es un fallo; es una nota de honestidad.

4. **§5.5 "Inferencia iterativa hasta 8 veces"**: verificado — `MAX_INFERENCE_PASSES: usize = 8` en `signature_inference_pass.rs:11`.

5. **§7.5.3 `base()`**: el reporte lo describe como una llamada directa al método del padre saltándose el dispatch dinámico. En el código, `Expr::BaseCall(BaseCallExpr)` se genera en el parser cuando el nombre del identificador es `"base"` (`grammar.lalrpop:791-806`); el codegen emite la llamada directamente al método del padre (`emit/expr/base_call.rs`).

6. **§7.2.5 "Range como built-in"**: verificado — `builtins::build_range_type_decl` (líneas 239-340 de `builtins.rs`) construye programáticamente el `TypeDecl` con campos `min`, `max`, `current` y métodos `next()`/`current()` con bodies reales. Se inyecta en el programa durante `reset_analysis_state`.

En síntesis, el reporte es fiel al código en un grado inusual para este cohort. La cantidad de páginas (~35) también es notable, y el nivel de profundidad en cada sección justifica su extensión — no hay relleno visible, cada apartado discute alternativas descartadas y razona su elección.

## 9. Fallas

Los tres bloques de tests bonus que fallan en CI **corresponden exactamente a features no marcados en el issue**:

- **`ok/macros` (8/8 fallas, categoría SYNTACTIC)**: no hay soporte para macros. El lexer no reconoce ningún token de macro y la gramática no tiene reglas asociadas. Coherente con lo declarado.
- **`ok/arrays` (8/8 fallas, categoría LEXICAL)**: no hay tokens `[` ni `]` en el lexer (`src/lexer/mod.rs:12-133`). Cualquier fuente que use notación de arreglos falla en el nivel léxico. Coherente con lo declarado.
- **`ok/lambdas` (6/6 fallas, categoría SYNTACTIC)**: no hay producción de lambda en la gramática. El backslash `\` no está en el lexer; no hay token `fn` para funciones anónimas. Cualquier programa con lambdas falla en el parser. Coherente con lo declarado.

**Ninguna de las tres omisiones es un bug**: son alcances no prometidos por la entrega. El techo bonificable, sin embargo, queda limitado a los `extras` (10/10 obtenidos).

Además, el reporte declara honestamente dos limitaciones conocidas del código enviado (§8):

- **Dispatch cascada O(n)** — no escala a cientos de tipos, pero es suficiente para los programas del curso.
- **Memory leaks** — todos los objetos se alocan con `malloc` sin `free` ni GC. Para programas de vida corta el SO libera la memoria; para programas de larga duración sería un problema.

Ninguna de las dos limitaciones afecta la puntuación de tests.

## 10. Conclusión

Hulk-Compiler es una entrega **completa, bien organizada y notablemente documentada**. Cumple el techo requerido (71/71 tests obligatorios) y también el techo de bonificación disponible dado el alcance declarado (10/10 extras). La coherencia entre el issue, el reporte y el código es alta: cada feature marcado tiene evidencia clara en el código, cada limitación conocida está reconocida en el reporte, y los features no marcados no se intentaron —lo que es una decisión de alcance defendible y sana—.

**Fortalezas técnicas destacadas:**

- **Dualidad `Iterable`/`Enumerable`**: separación explícita y correcta de dos protocolos de iteración con semántica diferenciada (self-iterator vs factory). Poco común entre las entregas del curso; el paralelo con Rust (`Iterator` vs `IntoIterator`) es explícito y bien justificado.
- **Splat notation con síntesis de interfaces refinadas**: sustituto pragmático de generics que evita introducir variables de tipo, unificación ni monomorfización, pero cubre el caso principal (iterar sobre colecciones homogéneas).
- **Varianza estructural** (covariante en retorno + contravariante en parámetros) con mensajes de error específicos y verificación en subtipado real de la jerarquía.
- **Codegen LLVM emitido como texto**: enfoque deliberado, con maquinaria propia para dispatch cascada + `phi`, tabla global de padres + función `hulk_is_subtype` en LLVM IR, y desugar del `for` en codegen (no en parser) para habilitar la distinción `Iterable`/`Enumerable`.
- **GUI eframe**: valor añadido único en este cohort (1 412 LOC de UI para editar, ejecutar y visualizar).
- **Reporte de 945 líneas** con análisis de decisiones, alternativas descartadas y limitaciones honestas. La calibración con el código es alta.

**Debilidades honestas:**

- **Dispatch O(n)** — reconocido en el reporte; irrelevante para programas del curso pero limitación de diseño.
- **Bug conocido en herencia + dispatch** — el reporte lo declara explícitamente en §6.4; no aparece en fallos de tests pero es una deuda técnica identificada.
- **Números unificados a f64** — pierde precisión para enteros grandes; decisión de simplicidad.
- **Memory leaks** — sin GC ni ARC; aceptable para el alcance académico.
- **Sin comentarios en el lenguaje** — el lexer solo salta whitespace; ninguna sintaxis para comentarios `//` o `/* */`.

**Balance final.** Entrega en el cuartil superior del cohort en términos de calidad del reporte, organización del código y coherencia entre lo prometido y lo entregado. La decisión de emitir LLVM IR como texto es defendible y ejecutada correctamente; la GUI adicional es un plus visible; la dualidad `Iterable`/`Enumerable` demuestra madurez conceptual. Los tres bloques de tests bonus fallidos (macros/arrays/lambdas) corresponden exactamente a features no marcados y no descuentan de la nota. Cumple con creces los requisitos del issue #27 y del curso.
