---
student: John Mauris López Ramos
issue: 40
repo: John31415/hulk-compiler
branch: main
date: 2026-07-02
---

# Evaluación técnica — Compilador HULK de John Mauris

## 1. Descripción arquitectónica

El proyecto es un compilador HULK escrito en **Rust 2024** (`Cargo.toml`, `edition = "2024"`) que produce ejecutables nativos vía LLVM 18. La topología es un pipeline clásico de 4 fases coordinado desde `src/main.rs`:

1. **Lexer** (`src/lexer/`) — `logos 0.15`.
2. **Parser** (`src/parser/`) — combinadores `chumsky 0.13`, split por precedencia y por tipo de expresión.
3. **Análisis semántico** (`src/semantic/`) — colección → registro → chequeos estructurales → tipado → monomorfización, produciendo un HIR (`TypedProgram`).
4. **Backend** (`src/backend/`) — `inkwell 0.9` sobre LLVM 18, con vtables por clase y despacho indirecto.

Adicionalmente:
- **Runtime C** (`runtime/runtime.c`, 104 líneas) — expone `hulk_fn_*` (`sin`, `cos`, `exp`, `sqrt`, `log`, `rand`, `print`, `print_number`), `hulk_string_concat[_space]`, `hulk_number_to_string`, `hulk_string_equals` y `hulk_unreachable_method` como *panic-slot* de vtable.
- **Prelude HULK** (`stdlib/prelude.hulk`, 14 líneas) — fusionado en el AST del programa del usuario después de parsear ambos por separado (`src/main.rs:63-100`). Define `protocol Iterable`, `type Range` y la función `range`.
- **Diagnósticos**: hay dos capas — la `Diagnostic`/`Label`/`ariadne::Report` interna (`src/diagnostics/render.rs:1-38`) y el impresor "contract" plano (`src/main.rs:231-238` con formato `(line,col) CATEGORY: message`). En `main` se usa **exclusivamente** el impresor contract; `ariadne` está enlazado pero nunca invocado en el binario `hulk` real.
- **Total de código**: ~12,700 líneas Rust en `src/`, sin contar snapshots.

El punto de entrada (`src/main.rs:24-133`) implementa el contrato exacto: exit codes 1/2/3 para lexical/syntactic/semantic, y compila a `output.ll` → `output.o` → `output` invocando a `llc` y `cc` externos (`src/main.rs:135-202`). El auto-descubrimiento prueba `llc, llc-20, llc-19, llc-18, llc-17` y `cc, clang, gcc` respetando las variables `HULK_LLC`/`HULK_CC`.

## 2. Lexer (logos)

`src/lexer/token.rs:9-129` define el enum `TokenKind` con macros `#[token]` y `#[regex]` de `logos`. Cubre todas las palabras clave del núcleo HULK (`let`, `in`, `function`, `if`, `elif`, `else`, `for`, `while`, `type`, `inherits`, `new`, `is`, `as`, `interface`, `protocol`, `extends`), operadores incluyendo `@`, `@@`, `:=`, `=>`, y — notablemente para las fallas — **`LBracket`/`RBracket` están declarados (`src/lexer/token.rs:97-99`) pero nunca consumidos por el parser**.

Whitespace y comentarios de línea (`//.*`) se ignoran via `logos::skip`. Cadenas y números pasan por validadores custom:

- `validate_process_number` (`src/lexer/token.rs:131-145`) — rechaza `LeadingZero`, `MalformedNumber` (múltiples `.` o `.` final) y `NumericOverflow` (infinito tras parse).
- `validate_process_string` (`src/lexer/token.rs:147-170`) — procesa escapes `\n`, `\t`, `\"`, `\\`; error en cualquier otro.

`src/lexer/lexer.rs:1-57` envuelve el iterador de `logos` en un `Lexer` que produce `Vec<Token>` con `Span` (offset inicial/final en bytes), añade un `EOF` sintético y acumula errores para reporte unificado.

## 3. Parser (chumsky combinators)

Uno de los aspectos más interesantes del proyecto: usa combinadores de `chumsky 0.13` en vez de un generador LALR/PEG.

`src/parser/program.rs:8-35` es el `program_parser`: `decl* expr? EOF`. Nótese que el cuerpo del programa es **opcional** — cuando falta se sustituye por un `ExprKind::Block(Vec::new())` sintético (`src/parser/program.rs:31-33`), lo que corresponde a la especificación relajada del contrato.

`src/parser/expr/mod.rs:24-61` construye la jerarquía de precedencia usando `recursive` de chumsky y una cascada boxed:

```
primary → new → postfix → unary → exponent (^ right-assoc)
       → product (*, /, %) → sum (+, -, @, @@) → comparison (<, >, <=, >=)
       → is → as → equality (==, !=) → logical_and (&) → logical_or (|)
       → assign (:=) or logical_or
```

Detalles finos:

- **Exponente asociativo a la derecha**: implementado con `Recursive::declare()` y auto-referencia en `src/parser/expr/binary.rs:6-22`.
- **`is`/`as` son unarios postfix opcionales** sobre la cara comparativa: aceptan un identificador de tipo como *rhs* (`src/parser/expr/binary.rs:65-131`).
- **Concatenación `@` y `@@`** tienen la misma precedencia que suma/resta (`src/parser/expr/binary.rs:37-49`), lo cual es una decisión de diseño razonable.
- **Postfix** (`src/parser/expr/postfix.rs`): sólo tres operadores — `(args)`, `.property`, `.method(args)`. **No hay `[index]` — el token `LBracket` nunca aparece en la gramática**.

Declaraciones (`src/parser/decl/`):

- **Función** (`function_decl.rs`): parámetros con tipos opcionales, retorno opcional, cuerpo `=> expr;` o bloque `{...}`. Los parámetros aceptan la anotación `TypeAnnotation::Star` (con `*`) para la extensión iterable.
- **Tipo** (`type_decl.rs:9-177`): parámetros de constructor opcionales, `inherits Parent(args)` opcional, cuerpo con atributos (`name = expr;`) y métodos (`name(params) => expr;` o bloque).
- **Protocolo** (`protocol_decl.rs`): acepta indistintamente `protocol` o `interface` (`src/parser/decl/protocol_decl.rs:79-91`), soporta `extends P1, P2` para herencia múltiple de protocolos, exige que los parámetros de método tengan tipo explícito (`params.then(type_name)`, `protocol_decl.rs:46-49`).

El parser emite errores como `chumsky::error::Rich` y los traduce vía `parser::error::rich_to_diagnostic` al formato interno (`src/main.rs:52-61`).

## 4. Análisis semántico + HIR

`SemanticAnalyzer` (`src/semantic/analyzer.rs:6-84`) orquesta cuatro pasadas:

1. **`install_builtins`** (`src/semantic/builtin.rs`) — inyecta `sqrt/sin/cos/exp/log/rand/print/print_number` y las constantes `PI`, `E`.
2. **`collect_declarations`** (`src/semantic/decl/collect.rs:7-77`) — primera pasada: registra nombres para permitir forward references. Funciones se registran con firma provisional `[Object; n] → Object`.
3. **`analyze_declarations`** — resuelve firmas reales, valida herencia (con detección de ciclos, `src/semantic/decl/inherit.rs`), procesa protocolos y constructores efectivos por herencia.
4. **`analyze_expr`** — chequeo de tipos con LCA para `if/else`, desazucarado del `for` a `let __iter/while` inline.

El **HIR tipado** (`src/semantic/hir.rs`) es una réplica del AST pero cada nodo lleva `TypeId` y la fase de monomorfización acumula `monomorphized_functions`, `monomorphized_types` y `monomorphized_methods` en orden topológico determinista (mantenido en tres pares de `HashMap` + `Vec<Key>` para preservar orden — `analyzer.rs:29-64`).

**TypeTable** (`src/semantic/types.rs`):

- Slots 0..3 fijos: `Object`, `Number`, `String`, `Boolean` (`types.rs:56-60`).
- `is_subtype_of` (`types.rs:106-204`) implementa el subtipado híbrido:
  - Identidad reflexiva.
  - Si el objetivo es un protocolo y la fuente es una clase: chequeo estructural miembro a miembro con covarianza del retorno y contravarianza de parámetros (`types.rs:133-193`).
  - Si el objetivo es un protocolo y la fuente también es un protocolo: BFS sobre la relación `extends`.
  - En caso general: cadena nominal hacia arriba (`types.rs:196-203`).
- `find_lca` (`types.rs:243-258`) — LCA para tipo unificado de `if/else` con fallback a `Object`.
- `resolve_type` (`types.rs:379-418`) — desazúcar `T*` a `Iterable$T` en la propia tabla: crea un protocolo sintético que hereda de `Iterable` con `next(): Boolean` y `current(): T`.

**Contexto semántico** (`src/semantic/context.rs`) mantiene pila de scopes, `current_type`, `current_method`, `current_function_return`, y tres pares de tablas para monomorfización (`generic_instances`+`instantiation_order`, `generic_type_instance_decls`+`type_instantiation_order`, `generic_method_instances`+`method_instantiation_order`).

**Desazucarado del `for`** (`src/semantic/expr/control_flow.rs:77-174`) — se hace en el HIR: comprueba subtipo de `Iterable`, extrae el tipo de `current()` como el tipo de la variable de bucle, y sintetiza:

```
let __iter_<span> = iterable in
    while (__iter_<span>.next()) {
        let x = __iter_<span>.current() in body
    }
```

Con nombre higiénico basado en el span (`__iter_{start}_{end}`).

## 5. Codegen (inkwell + LLVM 18)

`src/backend/context.rs:18-108` define `Backend<'ctx>` con `TypeRegistry`, `FunctionRegistry`, `RuntimeRegistry`, `MethodSlotRegistry` y una pila de scopes con `HashMap<String, PointerValue>`. Se declaran globales constantes `PI` y `E` en el módulo.

**Layout de objetos** (`src/backend/decl/decl_types.rs:63-250`):
- Cada tipo tiene un `StructType` opaco con el primer campo (`offset 0`) siempre `ptr` a la vtable, y a continuación los campos del padre (heredados por copia) seguidos de los atributos propios.
- Constructores mangleados como `hulk_ctor_<Type>` reciben `self: ptr` como primer parámetro y devuelven `ptr`. Un constructor no aloca — el llamador lo hace en `compile_new`.
- El primer paso del constructor almacena el puntero a la vtable global del tipo, luego llama al constructor del padre (con argumentos ya calculados en el HIR) y finalmente inicializa los atributos propios.

**Vtables** (`src/backend/method_slots.rs` + `src/backend/decl/decl_types.rs:268-331`):
- `MethodSlotRegistry` asigna un slot global único por *nombre* de método (empezando en 1, dejando 0 libre).
- Cada vtable global se construye como `{ i32 tag, [N x ptr] methods }` — el tag es el `TypeId` para chequeos `is`.
- Slots no cubiertos por la jerarquía de la clase se rellenan con `hulk_unreachable_method` como sentinel de pánico (correcto y defensivo).
- Herencia: al construir la vtable de un tipo, para cada slot se busca la implementación **empezando por el tipo actual y ascendiendo por la cadena `parent`** hasta encontrar el método o llegar al pánico (`decl_types.rs:288-311`).

**Despacho de métodos** (`src/backend/expr/postfix.rs:44-143`):
- Siempre indirecto: carga `vtable`, calcula el slot (`slot - 1` porque el array empieza en índice 0), extrae el `ptr` de la función y llama con `build_indirect_call`.
- Nota interesante: para reconstruir el tipo de la función indirecta usa la firma de la función *estáticamente* conocida en el tipo declarado (buscada por herencia en `postfix.rs:62-79`), y luego rearma un `FnType` con esos parámetros.

**`is`/`as`** (`src/backend/expr/binary.rs:254-349`):
- `is` para primitivos: constante en tiempo de compilación (`binary.rs:274-284`).
- `is` para objetos: carga el tag desde la vtable y compara contra la unión de todos los subtipos del objetivo (`binary.rs:286-304`), computando `OR` bit a bit.
- `as` es esencialmente un `bitcast` de punteros o pass-through de escalares (`binary.rs:307-349`) — **no** hace chequeo runtime del cast, algo que el reporte del estudiante reconoce parcialmente al hablar de type erasure.

**Aritmética** (`src/backend/expr/binary.rs:16-252`):
- Toda la aritmética en `f64` (`fadd`, `fsub`, `fmul`, `fdiv`, `frem`), potencia via intrínseco `llvm.pow.f64`.
- Comparación numérica con `FloatPredicate::OLT/OGT/OLE/OGE`.
- Concat `@` y `@@` — coerción implícita de `Number` a `String` vía `hulk_number_to_string` cuando hace falta (`binary.rs:397-422`).
- Igualdad de strings usa `hulk_string_equals` del runtime; comparación de otros punteros es igualdad de referencia.

**Emisión**: `src/backend/emit.rs` volca el módulo LLVM a `output.ll`. Luego `main.rs:165-202` lanza `llc -filetype=obj -relocation-model=pic`, compila `runtime/runtime.c` con `-Wall -O2 -ffast-math`, y enlaza estáticamente con `-no-pie -lm`.

## 6. Runtime (C)

`runtime/runtime.c` (104 líneas) provee:

- Conversión: `hulk_number_to_string(double) → char*` con `snprintf("%g", ...)`.
- Concatenación: `hulk_string_concat`, `hulk_string_concat_space`.
- Matemáticas: `hulk_fn_sin/cos/exp/log/sqrt`. `log(base, value) = ln(value)/ln(base)`.
- Aleatoriedad: `hulk_fn_rand()` con LCG semilla propia (no llama a `libc rand()`).
- I/O: `hulk_fn_print(char*) → char*` con `\n`, `hulk_fn_print_number(double) → double` con `%g\n`.
- Sentinela: `hulk_unreachable_method()` imprime a stderr y llama `exit(1)`.
- Igualdad: `hulk_string_equals` con `strcmp`.

Uso de `malloc` sin `free`: no hay memory management — todos los strings se filtran deliberadamente. El REPORT reconoce esto como limitación planeando refcounting como trabajo futuro (REPORT.md §14).

## 7. Features opcionales

Marcadas por el estudiante en el issue: **minimal, types, OOP+is/as, iterables, protocols**. Confirmado en código:

- **Minimal**: aritmética, bloques, `let ... in`, `if/elif/else`, `while`, funciones globales, tipos primitivos, concatenación `@`/`@@` — todo presente.
- **Types** (clases HULK): declaración, atributos con inicializador, métodos, `type P(x, y) { ... }` con parámetros de constructor. `src/semantic/decl/types.rs` (563 líneas).
- **OOP + is/as**: herencia simple con `inherits Parent(args)`, `base()`, override chequeado con arity/varianza (`SemanticErrorKind::InvalidOverride*`). `is` con vtable-tag, `as` como bitcast. Confirmado en `src/semantic/decl/inherit.rs`, `src/semantic/expr/binary.rs`, `src/backend/expr/binary.rs`.
- **Iterables**: azúcar `T*` con protocolos sintéticos `Iterable$T`, `for` desazucarado a `let __iter/while`. Ver `src/semantic/types.rs:379-418` y `src/semantic/expr/control_flow.rs:77-174`. Único iterable predefinido: `Range` en `stdlib/prelude.hulk`.
- **Protocols**: `protocol`/`interface` con `extends`, tipado estructural con covarianza/contravarianza correctas, chequeo de ciclos con DFS de tres estados y colisión de métodos con `ProtocolMethodCollision`. `src/semantic/decl/protocols.rs`.

**No marcadas y no implementadas**:
- **Vectors / arrays**: `LBracket`/`RBracket` están en `TokenKind` pero **no** son consumidos por ninguna regla del parser. No hay `ExprKind::ArrayLiteral` ni `ExprKind::Index`. Confirmado con `Grep`.
- **Functors / lambdas**: no hay `ExprKind::Lambda`, no hay `\x =>` ni sintaxis alguna. `Grep` de `lambda|closure` no encuentra nada.
- **Macros**: `Grep` de `macro|functor` no encuentra nada relevante (excepto macros de Rust internas).

**Adiciones sobre la base**:
- **Genéricos con monomorfización real**: funciones sin tipo anotado o cuyo parámetro es un protocolo se clasifican como `SymbolType::GenericFunction`. Los tipos con parámetros de constructor no anotados son `is_generic_template = true`. La instanciación se dispara en los sitios de uso (`analyze_generic_call` en `call.rs`, `analyze_generic_new` en `new.rs`, `analyze_generic_method_call` en `postfix.rs`), con caché por clave `(nombre, Vec<TypeId>)` y control de recursión vía `in_progress_instances`. El name mangling es `<base>$T1$T2...`. Ver `src/semantic/decl/methods_generic.rs` y `src/semantic/decl/types_generic.rs` (666 líneas). Esto es una extensión significativa y no trivial.
- **Herencia múltiple de protocolos** (`extends P1, P2`) con propagación de firmas por BFS y detección de colisión.
- **`interface` como alias sintáctico de `protocol`**.

## 8. Exactitud del reporte

REPORT.md tiene ~928 líneas / ~9800 palabras. Es un reporte de altísima calidad, con formato consistente y prosa técnica competente. Comparado con el código:

**Alta fidelidad**:
- Descripción del pipeline en §3 coincide 1:1 con `src/main.rs`.
- La tabla de módulos (§3.2) refleja la estructura real de `src/`.
- El sistema de tipos híbrido (§7) — herencia nominal + protocolos estructurales — se implementa exactamente como se describe. LCA, `is_subtype_of` con covarianza/contravarianza, y el diagrama del árbol de tipos primitivos coinciden con `types.rs`.
- El desazucarado de `T*` a `Iterable$T` (§10) está literalmente en `types.rs:379-418`.
- El desazucarado del `for` (§10.2) es exactamente el código de `control_flow.rs:124-173`.
- Monomorfización (§9): las cachés (`generic_instances`, `in_progress_instances`, `monomorphized_functions`), el name mangling `f$Number$String`, y la regla `GenericMethodOverrideNotAllowed` están todas en el código.
- Vtables y sentinela `hulk_unreachable_method` — coinciden.

**Reclamaciones matizadas**:
- §4.3 habla de renderizado con `ariadne` en consola, pero **`main.rs` sólo usa el formato contract plano**. La infraestructura de `ariadne` está en `src/diagnostics/render.rs:11-38` pero nunca se invoca en el binario producido. En pruebas locales podría usarse, pero no en la salida normal del compilador. Esto es una imprecisión menor.
- §8.3 dice "el segundo campo apunta a la vtable" cuando en realidad es el **primer campo (offset 0)** — probable error tipográfico, no de implementación.
- §12 dice que `Iterable` tiene `current(): Object`, y efectivamente `stdlib/prelude.hulk:3` lo declara así. Pero luego el desazúcar de `T*` inyecta `current(): T`, lo cual el reporte también dice correctamente en §10.

**Faltantes / limitaciones auto-reconocidas**:
- §14 lista honestamente: monomorfización que no puede override, inferencia recursiva conservadora, protocolos no usables como argumentos genéricos, azúcar `T*` acoplado exclusivamente a `Iterable`. Todo verificable en el código.
- El reporte **no menciona** que arrays (`T[]`) están planeados pero *sí* se propone en §14 como trabajo futuro. Correcto: no hay implementación.

**No hay claims falsas materiales**. El reporte describe lo que existe y lo hace con detalle apropiado.

## 9. Diagnóstico de fallas principales

Del CI del 2026-06-25 (71/71 obligatorios, 10/10 extras marcados). Las fallas reportadas:

### 9.1 `ok/macros/*` — 8 fallas sintácticas (esperado)

El estudiante **no** marcó macros en el issue. El parser no tiene reglas para macros (`Grep` confirma cero ocurrencias de `macro`/`syntax` como concepto sintáctico HULK). Cualquier test de la carpeta `ok/macros/` que use sintaxis `@!` u otras primitivas de macro fallará en la fase sintáctica. **No es un bug; es una feature no marcada**.

### 9.2 `ok/arrays/*` — 8 fallas sintácticas por `LBracket`

Causa raíz: `TokenKind::LBracket` **existe** en `src/lexer/token.rs:97` y por tanto el lexer sí lo tokeniza (no cae en `LexErrorKind`). Pero **ninguna regla del parser** consume `LBracket`:

- En `postfix.rs`, los postfix son sólo `(args)`, `.property` y `.method(args)`.
- En `primary.rs`, primary sólo reconoce variables y literales.
- No hay `array_literal_parser`, no hay `index_parser`.

Cuando aparece `[` en un programa (por ejemplo `let arr = [1, 2, 3];` o `arr[0]`), chumsky reporta un error de token inesperado en fase sintáctica. Consistente con el conteo de 8 fallas. **No marcado en el issue, correctamente rechazado**.

### 9.3 `ok/lambdas/*` — probables fallas

No hay `ExprKind::Lambda` ni sintaxis lambda. El token `Arrow` (`=>`) existe (`token.rs:108`) pero se usa para cuerpos inline de funciones/métodos (`function f() => expr;`) y de constructores parentales. Cualquier expresión lambda anónima (por ejemplo `x => x + 1` como valor) fallará. **No marcado en el issue**.

### 9.4 Resumen de cobertura

Del checklist del enunciado:

| Feature | Marcada | Implementada | Estado |
|---|---|---|---|
| minimal | sí | sí | ✅ |
| types | sí | sí | ✅ |
| OOP + is/as | sí | sí (con vtable-tag para `is` correcto) | ✅ |
| iterables | sí | sí (`T*` + `Iterable` + `for` desazucarado) | ✅ |
| protocols | sí | sí (con herencia múltiple y varianza) | ✅ |
| vectors | no | no (LBracket unused) | consistente |
| functors | no | no | consistente |
| macros | no | no | consistente |

**No hay evidencia de que ninguna feature marcada esté mal implementada.** Las fallas de CI corresponden 100% a features **no marcadas**. El compilador está internamente consistente con lo que promete.

### 9.5 Aspectos técnicos destacables

- **Uso de `chumsky` con precedencia manual boxeada** es raro en proyectos estudiantiles (la mayoría usan hand-written recursive descent). El código es legible y correcto.
- **Vtables con `hulk_unreachable_method` como sentinel** es una decisión defensiva madura; la mayoría de compiladores estudiantiles fallan silenciosamente en slots vacíos.
- **Monomorfización de genéricos** es una feature no exigida y no trivial. El estudiante la implementa con caching, orden topológico determinista y detección de ciclos de inferencia (`GenericInferenceFailed`).
- **Herencia múltiple de protocolos con BFS de propagación de firmas** — correcto.
- **`is` con vtable-tag** — más eficiente que rastrear la cadena de padres en runtime; requiere que cada vtable tenga el `TypeId` como primer campo, lo cual sí se hace en `decl_types.rs:317-319`.
- **Diagnósticos** dobles (`ariadne` interno + contract externo) — el `ariadne` acoplado pero no usado en `main` es un detalle que podría explicarse mejor.

### 9.6 Aspectos mejorables

- El uso de `panic!` en el parser cuando el target de una llamada no es un `Variable` (`src/parser/expr/postfix.rs:62`) es un antipatrón; debería ser un error de parseo recuperable.
- `String` como `PointerType` sin distinción del tipo puntero de otros objetos hace ambiguo el bitcast en `as`. El reporte lo reconoce como limitación.
- El backend no gestiona memoria: `malloc` sin `free` en todos los constructores de tipos, strings y `hulk_number_to_string`.
- El binario `hulk` no invoca `ariadne` — los usuarios finales sólo ven el formato contract.

En conjunto es un proyecto sobresaliente en calidad de implementación y sinceridad del reporte, con las fallas de CI perfectamente atribuibles a las features no marcadas.
