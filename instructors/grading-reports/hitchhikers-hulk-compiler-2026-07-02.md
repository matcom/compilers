---
student: Kevin Alejandro Torres Perera, Lianny de la Caridad Revee Valdivieso, Jocdan Lismar Lopez Mantecon
issue: 41
repo: MatCom-Developing-Team-10/The-Hitchhikers-Compiler
branch: main
date: 2026-07-02
---

# Evaluación técnica — Compilador HULK del equipo Hitchhiker's

## 1. Descripción arquitectónica

El proyecto entrega un compilador HULK escrito en **Rust edition 2024** (MSRV 1.85), organizado como un *workspace* de Cargo con **seis crates internos** más un binario, distribución que refleja las cinco fases clásicas del compilador con separación estricta. La estructura es notablemente disciplinada: `crates/hulk-ast/`, `crates/hulk-lexer/`, `crates/hulk-parser/`, `crates/hulk-semantic/`, `crates/hulk-ir/`, `crates/hulk-vm/` y el driver `hulkc/`. Total: ~9 100 LOC Rust propios más 836 LOC de gramática LALRPOP.

El manifiesto (`Cargo.toml:6-14`) declara los siete miembros con dependencias unidireccionales (`hulk-lexer → hulk-parser → hulk-semantic → hulk-ir → hulk-vm`, todas apoyadas en `hulk-ast` como contrato central). El perfil release fija `lto = "thin"` y `codegen-units = 1`. Las dependencias externas son mínimas y bien elegidas: `logos 0.16` para el lexer, `lalrpop 0.23` para el parser (con `lalrpop-util` en modo `lexer + unicode`), `thiserror 2` para diagnósticos y `clap 4.6` (declarado, aunque `main.rs` no lo usa efectivamente — es un residuo).

El **rasgo más distintivo** dentro del universo de entregas es la elección de backend: en vez de emitir código nativo o LLVM IR, el compilador implementa un **bytecode propio de máquina de pila** (98 instrucciones en `Instr`), lo ejecuta con una **VM de pila con recolector de basura mark-and-sweep** (`crates/hulk-vm/src/heap.rs`), y satisface el contrato `./output` de la cátedra generando un shell script auto-contenido que re-invoca al propio binario `hulk` en modo `exec` con el fuente embebido como heredoc (`hulkc/src/main.rs:134-175`). Es una elección pragmática y honesta: se declara explícitamente en REPORT.md §10 como una limitación conocida.

El pipeline orquestado por `hulkc/src/main.rs:69-86` en modo compile es: lectura → `hulk_parser::parse` → `hulk_semantic::analyze` → generación de `./output`. En modo `exec` (invocado por el output generado) suma `hulk_ir::lower_program` → `hulk_vm::Vm::run_program`.

## 2. Lexer (hulk-lexer crate)

Está en `crates/hulk-lexer/src/lib.rs` (587 LOC). Se apoya en **logos 0.16**, que compila un DFA eficiente a partir del enum `Token` con atributos `#[token(...)]` y `#[regex(...)]`. El enum expone 47 variantes (`lib.rs:18-189`): 18 palabras clave (incluyendo `interface`, `implements`, `extends`), 20 operadores/puntuación y 3 literales (Number, StringLit, Ident).

Decisiones específicas verificadas en el código:

- `**` se reconoce antes que `*` (`lib.rs:86-90`) por orden de declaración, garantizando que `2 ** 3` se tokenice como potencia.
- `@@` se declara antes que `@` (`lib.rs:100-104`).
- `self` y `base` no son *keywords*: se tokenizan como `Ident` (tests `self_and_base_are_identifiers` en `lib.rs:491-494`) y su semántica se resuelve en fases posteriores. El comentario del REPORT sobre esto es exacto.
- Comentarios de línea `//` se descartan mediante `#[logos(skip(r"//[^\n]*", allow_greedy = true))]` (`lib.rs:20`). No hay comentarios de bloque.
- Los identificadores exigen empezar con letra: `r"[a-zA-Z][a-zA-Z0-9_]*"` (`lib.rs:187`). El underscore inicial está explícitamente prohibido según A.4.7 del libro.

**Cadenas**: la regex es `r#""([^"\\]|\\.)*""#` (`lib.rs:181`). El pos-procesamiento `parse_string` en `lib.rs:263-285` reconoce solo `\n`, `\t`, `\\` y `\"` como escapes válidos; cualquier otro escape se preserva literalmente. Además, `invalid_escape_offset` (`lib.rs:292-306`) escanea la cadena buscando escapes no reconocidos y reporta `LexError` con el offset exacto del backslash ofensivo — es un cuidado que muchos entregas omiten.

El **adaptador LALRPOP** es `Lexer<'input>` (`lib.rs:334-368`), que implementa `Iterator<Item = Result<(usize, Token, usize), LexError>>`, exactamente el protocolo triple que LALRPOP exige. Los errores léxicos cargan `start`/`end` en bytes.

La suite de tests unitarios (12 casos, `lib.rs:373-585`) cubre keywords, operadores greedy, comentarios, span tracking y un programa HULK completo.

## 3. Parser (hulk-parser crate)

En `crates/hulk-parser/src/` con `lib.rs` (436 LOC) más `grammar.lalrpop` (836 LOC). El *build script* `build.rs` genera `grammar.rs` desde `grammar.lalrpop` en tiempo de compilación via `lalrpop::process_root()`. La API pública es una función única: `pub fn parse(source: &str) -> Result<Program, ParseError<'_>>` (`lib.rs:42-45`), que crea el lexer internamente.

**Gramática — 12 niveles de precedencia**. `grammar.lalrpop:376-773` implementa una cadena LR(1) explícitamente organizada:

| Nivel | No-terminal | Contenido |
|-------|-------------|-----------|
| 0 | `Expr` = `ClosedExpr \| OpenExpr` | split para control-flow como operando |
| 0.5 | `AssignExpr` | `x := e`, `obj.f := e` |
| 1 | `OrExpr` | `\|` |
| 2 | `AndExpr` | `&` |
| 3 | `NotExpr` | prefix `!` |
| 4 | `CompareExpr` | `==`, `!=`, `<`, `<=`, `>`, `>=` |
| 5 | `TypeOpExpr` | `is`, `as` |
| 6 | `ConcatExpr` | `@`, `@@` (right-assoc) |
| 7 | `AddExpr` | `+`, `-` (left-assoc) |
| 8 | `MulExpr` | `*`, `/`, `%` (left-assoc) |
| 9 | `UnaryExpr` | prefix `-` |
| 10 | `PowExpr` | `^`, `**` (right-assoc) |
| 11 | `PostfixExpr` | `.method(...)`, `.field`, `[idx]` |
| 12 | `AtomExpr` | literales, `(...)`, `{...}`, `new`, `[...]`, ident/call |

Detalles verificables:

- **`let` multi-binding desugarado**: `grammar.lalrpop:413-423` fold sobre las bindings de derecha a izquierda produce `Let` unarios anidados. El AST posterior nunca ve un `let a=1, b=2 in ...` — el checker razona sobre un binding por vez. Confirmado con el test `parses_multi_let_desugars_to_nested` (`lib.rs:170-179`).
- **Potencia asociativa por la derecha**: `PowExpr` recursa sobre `UnaryExpr` a la derecha (`grammar.lalrpop:566`), confirmado por el test `parses_power_right_associative`.
- **`-2^2` = `-(2^2)`** (convención matemática): `UnaryExpr` desciende a `PowExpr`, así que `-` binds más suelto que `^` pero más apretado que `*`. Verificado por `unary_minus_binds_looser_than_power` (`lib.rs:97-105`).
- **`if` obligatorio con `else`** (`grammar.lalrpop:792-806`): sin `else` la producción no reduce; consistente con "`if` es expresión, todas las ramas producen un valor".
- **Split open/closed** para permitir control-flow como operando (`grammar.lalrpop:376-410`, comentario ~80 líneas): resuelve la ambigüedad de `total + if (c) 1 else 0` haciendo que la cola de la cadena open siempre termine en `CtrlAtom`. Es una solución técnicamente elegante y — verificado por dos tests — funcional.
- **Vector literal y comprensión** (`grammar.lalrpop:642-657`): `[]`, `[e0, e1, ...]` y `[elem | x in iter]`. Los elementos se parsean al nivel `AndExpr` para que el `|` del generator sea inequívoco.
- **Tipos con parámetros genéricos** (`grammar.lalrpop:99-107`): la producción `TypeRef` reconoce `T`, `List[T]`, `T*` (iterable), `T[]` (vector).

**Cobertura de declaraciones**:
- `InterfaceDecl` (`grammar.lalrpop:170-195`) con `extends` y firmas de método.
- `TypeDecl` (`grammar.lalrpop:201-235`) con dos formas (con y sin parámetros constructor), `inherits`, `implements`.
- `FunctionDecl` (`grammar.lalrpop:316-343`) con dos formas (inline con `=>` o bloque `{...}`) y parámetros genéricos opcionales.

**El AST** (`crates/hulk-ast/src/lib.rs`, 420 LOC) define 22 variantes de `ExprKind` cubriendo literales, `Ident`, `SelfExpr`, `BinOp`, `UnOp`, `Call`, `MethodCall`, `Base`, `GetField`, `Let`, `Assign`, `AssignField`, `If`, `While`, `For`, `Block`, `New`, `Is`, `As`, `Vector`, `VectorComp`, `Index`. Cada nodo `Expr` carga un `Span` compacto (`lo: u32`, `hi: u32`), diseño coherente con el resto del pipeline.

**Notable ausencia**: no hay variante `Lambda` ni `FunctionType`. El compilador **no soporta funciones como valores de primera clase** en el AST — esto será determinante en §6 y §8.

Tests: 30 casos en `lib.rs:47-435` más las suites `tests/generics.rs` (119), `tests/interfaces.rs` (119), `tests/top_sequence.rs` (45).

## 4. Análisis semántico (hulk-semantic crate)

El crate está organizado en cinco módulos (`crates/hulk-semantic/src/`):

- `types.rs` (578 LOC) — `Type`, `TypeCtx`, `MethodSig`, `FunctionSig`, `TypeInfo`, `InterfaceInfo`, conformidad y LCA.
- `env.rs` (47 LOC) — `Env` de scopes anidados con shadowing.
- `error.rs` (141 LOC) — 25 variantes de `SemError`, todas con `span()`.
- `check.rs` (2 205 LOC) — el checker completo.
- `lib.rs` — re-exports y documentación del pipeline.

**Ocho pasadas — no cuatro como dice el REPORT**. La función `analyze` (`check.rs:2190-2205`) ejecuta:

1. `collect` — nombres de tipos, interfaces y funciones; rechaza duplicados, herencia de builtins, ciclos.
2. `sign` — llena firmas de métodos, funciones y constructores; resuelve tipos anotados.
3. `infer_ctor_params` — infiere parámetros no anotados del constructor desde los argumentos de `new T(...)`.
4. `infer_params` — infiere parámetros no anotados de funciones/métodos desde su uso en el cuerpo.
5. `infer_returns` — walk hasta fixpoint del cuerpo para tipos de retorno no anotados.
6. `check_interfaces` — valida implementaciones de interfaz.
7. `check_overrides` — firmas idénticas entre override e implementación heredada (A.7.4).
8. `check_bodies` — camino principal de type checking con acumulación de errores.

Esto es una discrepancia menor pero notable: el REPORT §6 lista solo cuatro pasadas y omite `infer_ctor_params`, `infer_params`, `infer_returns` y `check_interfaces`, precisamente las que dan al compilador su potencia real (inferencia A.9 e interfaces extension).

**Tipos** (`types.rs:16-36`): enum con `Number`, `String`, `Boolean`, `Object`, `User(String)`, `Generic(String, Vec<Type>)`, `Param(String)`, `Iterable(Box<Type>)`, `Vector(Box<Type>)`, y **`Error` como valor centinela**. El *poison* `Type::Error` es transparente en `conforms` y en `lca` (`types.rs:310-312, 519-523`), evitando cascadas de mensajes derivados de un solo fallo. Esta es una elección de ingeniería correcta y estándar en compiladores serios.

**Conformidad `conforms(a, b)`** (`types.rs:309-381`): implementa las reglas del libro (A.8.4) con extensiones bien pensadas:
- Reflexiva; `Object` como top; primitivas solo conforman con ellas mismas o con `Object`.
- Genéricos son **invariantes**: `List[Animal] ≰ List[Object]` (comentario explícito en `types.rs:6-9`). Elección teóricamente defendible en un lenguaje docente.
- **Iterables** (`types.rs:322-330`): un `Iterable(elem)` acepta otro iterable de elemento conforme, o un tipo de usuario que implemente el protocolo iterable (`next`/`current`) con `current()` conforme.
- **Interfaces** (`types.rs:360-365`): dos modalidades — **nominal** vía `implements_interface` (walk sobre la cadena de herencia buscando `implements` transitivo) y **estructural** vía `structurally_implements` (verifica que el tipo provea cada método requerido con firma matching). Ambas modalidades están implementadas y son visibles en el código. Verificado con la suite `tests/interfaces.rs` (244 LOC).

**LCA** (`types.rs:514-544`): construye la cadena de ancestros de `a`, luego camina desde `b` hacia arriba buscando el primer ancestro común. `Type::Error` es transparente (devuelve el otro tipo). Usado para tipar `if`/`elif`/`else` cuando las ramas producen tipos distintos.

**Substitution** (`types.rs:566-577`): para métodos/atributos de tipos genéricos (`List[T].head → T`), la resolución del tipo aplica un `HashMap<param → concrete>` en el punto de uso. Esto habilita el uso genérico real, no un "generics-in-name-only".

**Errors** (`error.rs`): 25 variantes cubren `ReservedName`, `ReservedTypeName`, `UndefinedVariable`, `UndefinedFunction`, `UndefinedType`, `Mismatch`, `InheritBuiltin`, `CyclicInheritance`, `DuplicateType`, `DuplicateFunction`, `OverrideSignatureMismatch`, `Arity`, `NoSuchAttribute`, `NoSuchMethod`, `SelfAssign`, `NonSelfFieldAssign`, `BaseOutsideOverride`, `BaseNoParentMethod`, `NotAnInterface`, `MissingInterfaceMethod`, `InterfaceSignatureMismatch`, `CannotInstantiateInterface`, `NotIterable`, `NotIndexable`. Cada una carga su `Span` y el REPORT declara que **cada variante tiene al menos un test negativo**, hecho verificable en `crates/hulk-semantic/tests/integration.rs` (702 LOC).

## 5. IR (hulk-ir crate) y VM (hulk-vm crate con heap+GC)

### 5.1 Representación intermedia

El crate `hulk-ir` está concentrado en un único `src/lib.rs` de **1 663 LOC**. Define `Instr` (`lib.rs:97-229`) con 65+ variantes clasificadas por categoría: literales, manipulación de pila (`Pop`, `Dup`), aritmética, booleanos con cortocircuito, comparación, concatenación, variables (`LoadVar`, `StoreVar`, `BeginScope`, `BindVar`, `EndScope`), control (`Label`, `Jump`, `JumpIfFalse`), funciones (`Call`, `Ret`), builtins matemáticos (`Sqrt`, `Sin`, `Cos`, `Exp`, `Log`, `Rand`), OOP (`NewObject`, `GetField`, `SetField`, `CallMethod`, `CallBase`, `IsType`, `AsType`), y **vectores** (`MakeVector`, `Index`, `VecPush`).

El diseño es notablemente pulido:
- `Value` (`lib.rs:39-92`) es enum de 5 variantes: `Num(f64)`, `Bool`, `Str(String)`, `Nil`, `Object(ObjectId)`. Las strings son ownership normal de Rust, no GC'd; solo los objetos viven en el heap.
- `ObjectId(u32)` (`lib.rs:33-34`) es un handle opaco. `PartialEq` de `Value::Object` compara por identidad de handle (`lib.rs:73-74`), no estructural.
- La `lower_program` produce un `IrProgram` con `funcs: HashMap<String, IrFunc>`, `types: HashMap<String, IrTypeInfo>` y `entry: Vec<Instr>`.

**Lowering de constructores** (`lib.rs:806-878`, `lower_constructor`): implementa el default-forwarding de A.7.3 (`effective_ctor_param_names` en `lib.rs:742-760`) — si `type Child inherits Parent` no da parámetros propios ni argumentos explícitos, hereda los parámetros del padre. El código camina la cadena leaf → root inicializando atributos y abriendo un scope por eslabón para que los parámetros del ancestro correcto sean visibles. El comentario técnico (`lib.rs:795-810`) es preciso y correcto.

**Método `Base`** (`lib.rs:491-505`, y `CallBase` en `lib.rs:210`): resuelve `base(...)` con la instrucción `CallBase(parent_type, current_method, n)`. La resolución empieza desde `parent_type` y camina hacia arriba en la cadena de herencia, por lo que un método declarado por un abuelo (no el padre inmediato) también se encuentra — un caso frecuentemente ignorado por otras implementaciones.

**`for` desugarado** al protocolo iterable (`lib.rs:406-444`): `for (x in it) body` se compila a `let iter = it.iter() in while (iter.next()) let x = iter.current() in body`. La instrucción `CallMethod("iter", 0)` — cuando `iter` no está definido — el VM lo trata como identidad (comentario `lib.rs:414-418`). Esto permite que `range(...)` (que es su propio iterador) siga funcionando sin código especial.

**Vectores** (`lib.rs:519-577`): el literal `[e0, e1, ...]` compila a `MakeVector(n)`. La comprensión `[elem | x in it]` desugara a `let acc = [] in for(x in it) acc.push(elem); acc`, usando la instrucción `VecPush`. En runtime un vector es un objeto con `type_name = "__Vector"` y elementos en claves `"0".."n-1"` más `__len`. Es un diseño consistente y aprovechado por el GC como cualquier otro objeto.

### 5.2 Máquina virtual

`crates/hulk-vm/src/lib.rs` (1 576 LOC) más `heap.rs` (276 LOC). El intérprete es un dispatch de `match &instrs[ip]` sobre las variantes de `Instr`, con `stack: Vec<Value>` y `scopes: Vec<HashMap<String, Value>>` (`lib.rs:93-111`).

**Detalles cuidados**:
- **`Vm::run_program`** (`lib.rs:149-166`) ejecuta el programa en un **thread dedicado con 256 MB de stack** para admitir recursión profunda que reventaría el stack principal.
- **`DEFAULT_MAX_CALL_DEPTH = 10_000`** (`lib.rs:20`): límite de profundidad de recursión reportado como `VmError::StackOverflow` en lugar de abortar por overflow nativo.
- **Suspended `Frame`s** (`lib.rs:76-79`, `call_stack: Vec<Frame>`): los frames del caller se materializan en el VM y no en la pila de Rust, para que sus objetos permanezcan **alcanzables desde el GC root set** durante llamadas anidadas. Es un detalle sofisticado que muchos implementadores pierden.
- **Cortocircuito**: `And` y `Or` se compilan con `Label`/`JumpIfFalse` (`hulk-ir/src/lib.rs:317-318`, funciones `lower_and`/`lower_or`), no como instrucción binaria. Verificado por `crates/hulk-vm/tests/short_circuit.rs`.

**Heap con GC mark-and-sweep** (`heap.rs`): el diseño es clásico y correcto:

- `Slot::Live(Object) | Slot::Free` (`heap.rs:29-32`), `Vec<Slot>` como storage.
- `Heap::alloc` (`heap.rs:72-82`) reutiliza slots de `free_list` antes de crecer el vector.
- `Heap::collect` (`heap.rs:129-163`) implementa mark-and-sweep depth-first desde las roots, marca alcanzables, sweeper libera los no marcados.
- **Threshold configurable** vía `HULK_GC_THRESHOLD` (`heap.rs:56-68`), default 1024 asignaciones antes de colectar.
- **Roots** (`lib.rs:191-200`): `stack` + `scopes` actuales + `call_stack` frames suspendidos.
- **Reclama ciclos correctamente** — verificado por `heap.rs:254-263` (`collect_reclaims_cycles`, dos nodos con `.next` mutuamente apuntándose son ambos liberados sin roots).

Suite de tests: `heap.rs:199-275` (7 tests unitarios sobre el heap) más `crates/hulk-vm/tests/gc.rs` (143 LOC de integración GC).

Los tres specs `vm-v2.spec.md`, `vm-v3.spec.md`, `vm-v4.spec.md` (v4 introduce el GC) muestran que el diseño evolucionó por iteraciones documentadas — evidencia de trabajo serio.

## 6. Features opcionales

Comparado con la marca en el issue (minimal, types, OOP+is/as, iterables, protocols; NO vectors, functors, macros), lo verificado empíricamente:

- **minimal**: implementado. Todas las categorías A.2–A.6 (aritmética, booleanos, strings, bloques, funciones, let, if/elif/else, while, for/range) están en el AST, se tipan y se ejecutan.
- **types**: implementado. Anotaciones opcionales, inferencia de parámetros no anotados (A.9.3, en `infer_params`), inferencia de retornos (`infer_returns`), inferencia de parámetros constructor (`infer_ctor_params`). Suite `tests/hulk_std/a9_param_inference.hulk` pasa.
- **OOP + is/as**: implementado con herencia, override, `base(...)`, despacho virtual, `self`, atributos privados accesibles solo vía `self`. `Instr::IsType` y `Instr::AsType` (`hulk-ir/src/lib.rs:213-216`) implementan runtime type test y downcast.
- **iterables/protocols**: implementados. `check_bodies` requiere `next()` y `current()` sobre el objeto del `for`; `Iterable(T)` es un tipo estructural del sistema de tipos. `types.rs:476-491` (`iterable_element_of`) resuelve el tipo del elemento inferido.
- **vectors**: **implementados también**, contra la marca del issue. `MakeVector`, `Index`, `VecPush`, `[e0, ...]`, `[elem | x in it]`, `v[i]`, `v.size()`. Suite `tests/extension/generics.hulk` pasa. Pero (importante) — la sintaxis implementada es la del libro HULK (`[1, 2, 3]`), **no la de la rúbrica de la cátedra** (`{10, 20, 30}` o `new Number[5]`); ver §7 y §8.
- **interfaces**: implementadas con dos modalidades — nominal (`implements`) y estructural. `interface Greeter { greet(): String; }`. `implements`. `extends`. Suite `tests/extension/interfaces.hulk` pasa. Pero (importante) — la palabra clave implementada es `interface`, **no `protocol`** como espera la rúbrica; ver §8.
- **generics**: implementados. `List[T]`, `Map[K, V]`, funciones `function map[T, U](...)`, `Type::Generic`, `Type::Param`, substitución. Erasure en runtime. Suite `tests/extension/generics.hulk` pasa.
- **functors**: NO implementados. Sin sintaxis de composición explícita en la gramática.
- **macros**: NO implementados. La palabra `define` no aparece en la gramática.
- **lambdas**: NO implementados. No hay `ExprKind::Lambda` en el AST ni sintaxis de tipo función (`(A) -> B`).

## 7. Exactitud del reporte

REPORT.md son 318 líneas / 2 640 palabras — dentro del rango de la rúbrica (≥1500). Su calidad expositiva es alta. Sin embargo, hay imprecisiones concretas:

1. **§6 subestima las pasadas**. Dice "cuatro pasadas" pero `analyze` en `check.rs:2190-2205` ejecuta **ocho** (collect, sign, infer_ctor_params, infer_params, infer_returns, check_interfaces, check_overrides, check_bodies). La pipeline real es más impresionante que la descrita. Además, `env.rs` (referenciado explícitamente en el pipeline del REPORT) es solo 47 LOC — el trabajo pesado está en `check.rs`.

2. **§7 REPORT dice "diecisiete variantes"** de `SemError`; el conteo real es **25** (contadas en `error.rs:8-110`). La imprecisión resta valor al conteo, aunque el punto general (acumulación en vez de panic) es correcto.

3. **§7 describe el for como `for (x in v)`** con "el paso de un vector donde se espera un iterable T\* funciona sin código especial". Correcto, pero mezcla la descripción del *lowering* (`iter()`+`next()`+`current()`) con la del sistema de tipos, cuando de hecho el REPORT no menciona el desugaring a `while` que es lo que realmente ocurre en `hulk-ir/src/lib.rs:406-444`.

4. **§10 admite `output` como wrapper** — honestidad reconocible. Pero no comenta el shell heredoc con hash-derived delimiter (`hulkc/src/main.rs:146-159`), que es una precaución adicional para evitar colisiones con el fuente.

5. **§7 declara "conformidad estructural de HULK con jerarquía de herencia"** para el sistema de tipos general, sin explicitar la elección de **invarianza en genéricos**, que sí está en el código (`types.rs:6-11`) y es un compromiso teórico digno de mencionar.

6. El REPORT **no menciona explícitamente** las limitaciones más consecuentes para la rúbrica:
   - Palabra clave `interface` en vez de `protocol`.
   - Sintaxis de vectores `[1,2,3]` sin `{1,2,3}` ni `new T[n]`.
   - Ausencia total de lambdas.
   - Ausencia total de macros.
   
   Estos son puntos donde el compilador difiere del test-set esperado; la §10 los pinta como "casos específicos documentados en el seguimiento interno" sin nombrarlos.

En conjunto, el REPORT es fuerte técnicamente pero **subvende** partes del trabajo (por errores de conteo) y **sobrevende** en compatibilidad al minimizar las diferencias sintácticas con la rúbrica.

## 8. Diagnóstico de fallas principales

Los CI del 2026-06-22 muestran **71/71 obligatorios + 10/10 extras pasando**, con fallos categorizados en `ok/macros` (8, todos sintácticos), `ok/arrays` (7-8 sintácticos), `ok/lambdas` (probable, sin datos completos) y `ok/interfaces` (desconocido). Los verifiqué compilando el binario y ejecutándolo contra los tests estándar de la cátedra:

**Verificación empírica**:

```
$ ./hulk tests/hulk/ok/lambdas/lambda_basic.hulk
(1,8) SYNTACTIC: unexpected token "(", expected one of IdentTok
```
`lambda_basic.hulk` empieza con `let f: (Number) -> Number = function (x: Number): Number -> x * 2`. La gramática exige `function <name>` (`grammar.lalrpop:316-343`) — no admite `function` seguido de `(`. Además `TypeRef` no admite `(A) -> B` como tipo de función. **Todos los lambda tests fallan por parser**.

```
$ ./hulk tests/hulk/ok/macros/simple_define.hulk
(1,8) SYNTACTIC: unexpected token "double", expected one of "is", "as", ...
```
`define` no es keyword; el token `Ident` con valor "define" al principio es tratado como identificador y el parser no puede reducir a nada. **Todos los macro tests fallan por parser**.

```
$ ./hulk tests/hulk/ok/arrays/array_basic.hulk
(1,30) SYNTACTIC: unexpected token "5", expected one of IdentTok
```
El fuente hace `new Number[5]`. La gramática de `NewExpr` (`grammar.lalrpop:829-836`) es `"new" IdentStr GenericArgs? "(" args ")"` — no admite `new T[n]`. Adicionalmente, `array_literal.hulk` usa `{10, 20, 30}` para literal de vector; la gramática solo reconoce `[10, 20, 30]`. **Todos los array tests fallan por parser**.

```
$ ./hulk tests/hulk/ok/interfaces/interface_basic.hulk
(1,10) SYNTACTIC: unexpected token "Printable", expected one of ...
```
El fuente empieza con `protocol Printable { ... }`. El lexer emite `Ident("protocol")` y el parser espera `interface`/`type`/`function`. **Todos los interface tests fallan por parser**. Nótese que el compilador **sí implementa el análisis semántico correcto de interfaces** con conformidad nominal y estructural — el problema es puramente léxico/gramatical (`interface` vs `protocol`).

**Causa raíz común**: el equipo implementó el HULK **del libro del curso** (`docs/Hulk - The Book.pdf`, `docs/Hulk - Required Spec.pdf`) fielmente. La gramática, el sistema de tipos y el semantic checker corresponden con precisión a esa especificación. Pero la rúbrica de la cátedra (`compilers/tests/hulk/ok/*`) usa una variante sintáctica distinta:

| Concepto | Libro / Hitchhikers | Rúbrica cátedra |
|----------|---------------------|-----------------|
| Interfaz | `interface X { ... }` | `protocol X { ... }` |
| Función anónima | (no soportada) | `function (x: T) -> body` |
| Tipo función | (no soportado) | `(A) -> B` |
| Vector literal | `[1, 2, 3]` | `{1, 2, 3}` o `[1, 2, 3]` |
| Vector tamaño | (no soportado) | `new Number[5]` |
| Vector auto-init | (no soportado) | `new Number[5]{ i -> i * 2 }` |
| Macros | (no soportado) | `define name(x): T -> body;` |

Fix aproximado:
- **Interfaces**: 1 línea de lexer (agregar `#[token("protocol")]` con alias). El resto ya funciona.
- **Lambdas**: cambio invasivo. Requiere `ExprKind::Lambda`, `TypeRef::Function`, tipo `Type::Function`, extensión de conformidad, y un mecanismo de closures en la VM (captura del entorno) o transformación a objeto con método `apply`. Estimado ~600-1000 LOC.
- **Arrays `new T[n]`**: extender `NewExpr` para reconocer `new IdentStr "[" Expr "]"`, y añadir builtin `__array_alloc(n)` en el IR/VM. Estimado ~150 LOC.
- **Array auto-init `new T[n]{ i -> expr }`**: requiere lambda (previa a implementar). Sin lambda, imposible.
- **Macros**: implementación tipo `define` requiere fase de expansión previa al lexing/parsing o un nuevo tipo de declaración `MacroDecl` sustituida en el AST. Estimado ~300-500 LOC.

En resumen, el compilador es una implementación **conceptualmente correcta, arquitectónicamente sólida y técnicamente rica** del HULK del libro — con un sistema de tipos que supera lo mínimo (genéricos con substitución, interfaces con conformidad estructural, LCA, poison propagation) y un backend original con VM propia y GC funcional. La distancia con la rúbrica de la cátedra es una brecha **de superficie sintáctica**, no de capacidad, pero la brecha es lo suficientemente grande para que categorías enteras de tests fallen sin diagnóstico útil (todos son errores sintácticos genéricos del parser LALRPOP).
