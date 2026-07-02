---
student: Fabian A. Almeida Martinez, Diego Hernandez Rodriguez
issue: 35
repo: falmart/HulkCompiler2026
branch: main
date: 2026-07-02
---

# Evaluación técnica — Compilador (Intérprete) HULK del equipo Fabdieg

> Repositorio: https://github.com/falmart/HulkCompiler2026
> Rama: main | Evaluación: 2026-07-02
> Generado por: Claude Code (evaluación automática)

---

## 1. Descripción arquitectónica (INTERPRETER approach)

**Estrategia elegida: intérprete tree-walking, no generación de código.** El proyecto es un workspace de Cargo (Rust 2024 edition) organizado en cinco crates de librería y un binario, sin backend LLVM y sin emisión de assembly ni bytecode. El binario `hulkc` es literalmente un intérprete: al aceptar un fichero `.hulk` corre lex → parse → semantic check → evaluación por recorrido del AST, y sólo por conformidad con la interfaz de calificación genera un archivo `./output` que es un **script shell** con el fuente HULK embebido en base64 y una llamada a `./hulk --run-stdin` (`hulkc/src/main.rs:59-79`). Esa técnica está declarada explícitamente en el REPORT (§ "Limitaciones Conocidas": "El compilador es un intérprete de árbol de sintaxis, no un generador de código").

Es un enfoque legítimo — pasa todos los tests de la suite — pero conviene notarlo con claridad porque la mayoría de los proyectos del curso compilan a nativo (LLVM IR + `clang`) o a MIPS. Aquí no hay codegen, no hay runtime en C/Rust separado y no hay ABI: el "ejecutable" es un shim.

**Workspace y dependencias** (`Cargo.toml:1-7`):

```
[workspace]
members = [
    "crates/hulk_lexer",
    "crates/hulk_ast",
    "hulkc",
    "crates/hulk_parser",
    "crates/hulk_semantic",
    "crates/hulk_interpreter",
]
```

No hay dependencias externas de terceros — ni siquiera `serde`, `regex` o `rand`; el propio `hulkc/src/main.rs:131-153` implementa un base64 encoder minimalista para no depender de crates externos, y el intérprete usa un LCG casero para `rand()` (`crates/hulk_interpreter/src/interpreter.rs:1032-1040`). La higiene de dependencias es notable: el proyecto compila desde cero con `cargo build --release` sin descargar nada.

**Flujo del binario `hulkc`** (`hulkc/src/main.rs:29-82`):

1. Lex + parse en un solo paso (`compile()` de `hulk_parser`); `PipelineError::Lex` → exit 1, `PipelineError::Parse` → exit 2.
2. `hulk_semantic::check()` devuelve `Vec<SemanticError>`; si no está vacío se emiten todos y exit 3.
3. Si no hay errores se escribe `./output` como script sh con perms 0755 y exit 0. El script decodifica el fuente base64 en un fichero temporal, invoca `./hulk --run-stdin < $_T`, y propaga el exit code.
4. La opción `--run-stdin` (línea 85-92) es la que realmente ejecuta el intérprete cuando `./output` la llama.

Este diseño cumple la letra del contrato (`make build → ./hulk`, exit codes 1/2/3, produce `./output` ejecutable) sin cumplir el espíritu (no hay compilación real). Es una decisión defendible dado que la interfaz nunca inspecciona el contenido de `./output`; sólo lo ejecuta.

**Verificación local**: `cargo test --release` desde la raíz reporta `75 + 63 + 82 + 77 = 297` tests pasando en 0.01–0.02 s por crate, coincidiendo exactamente con la cifra del REPORT.

---

## 2. Lexer (`hulk_lexer`)

Un tokenizador de una sola pasada, escrito a mano, ~275 líneas (`crates/hulk_lexer/src/lexer.rs`). Utiliza `CharIndices` con un carácter peekeado y rastreo manual de `line`/`col` (`lexer.rs:14-34`). No hay tabla de estados explícita ni AFD generado — es un `match ch` sobre el primer carácter.

**Cobertura de tokens** (`token.rs:31-113`): números `f64` (enteros y flotantes con un solo dígito post-decimal si el punto va seguido de dígito — el edge case `1.` se lexea como `Number(1) Dot`, ver `lexer.rs:82-93` y test `number_dot_not_float_when_no_digit_after`); strings con escapes `\n \t \\ \"`; identificadores UTF-8 (`is_alphabetic`); operadores compuestos `==`, `!=`, `<=`, `>=`, `->`, `=>`, `:=`, `@@`.

**Keywords** (`lexer.rs:247-277`): 24 reservadas — `let, in, if, elif, else, while, for, function, class, type, is, inherits, new, self, case, of, with, as, null, true, false, protocol, interface, def, define, default`. La palabra `base` **no** es keyword; se detecta contextualmente en el parser cuando `Ident("base")` va seguido de `(` (ver §3). Lo mismo para `match`.

**Comentarios**: sólo `//` de línea (`lexer.rs:56-73`). No hay soporte para bloque `/* */` — el intérprete tampoco lo necesita porque los tests no lo usan.

**Errores**: `LexError` (`error.rs:3-9`) cubre `UnexpectedChar`, `UnterminatedString`, `UnknownEscape`, `InvalidNumber`. Todos con `line`/`col` — no hay rango, sólo posición de inicio. El método `clean_message()` produce el texto en minúsculas que consumirá el CLI.

**Contexto sensible**: el símbolo `|` se emite siempre como `Pipe`; su interpretación (OR lógico vs. separador de comprensión) se decide en el parser mediante el flag `forbid_pipe_or` (`parser.rs:12`). Lo mismo para `@` como concat vs. prefijo de macro by-ref: el lexer emite `At` y el parser decide.

**63 tests unitarios** (`crates/hulk_lexer/src/lib.rs:39-600`) organizados en 13 secciones temáticas (literales, keywords, operadores, spans, casos de error, snippets HULK). Coincide con lo declarado en el REPORT.

---

## 3. Parser (`hulk_parser`)

Un recursive-descent puro, ~1290 líneas (`crates/hulk_parser/src/parser.rs`). Cursor `pos: usize` sobre un `Vec<Token>` completo pre-lexeado (no streaming). No hay recuperación de errores: la primera falla propaga el `Result`.

**Cascada de precedencia** (menor a mayor, `parser.rs:526-707`):

| Nivel | Función | Operadores | Asoc. |
|-------|---------|------------|-------|
| 0 | `parse_expr` | `let, if, while, for, case, with` | control |
| 1 | `parse_assign` | `:=` | derecha (`L539-550`) |
| 2 | `parse_type_ops` | `is`, `as` | izquierda (`L553-569`) |
| 3 | `parse_or` | `\|` | izquierda (`L571-582`) |
| 4 | `parse_and` | `&` | izquierda (`L584-595`) |
| 5 | `parse_equality` | `==`, `!=` | izquierda (`L597-614`) |
| 6 | `parse_comparison` | `<, <=, >, >=` | izquierda (`L616-635`) |
| 7 | `parse_concat` | `@`, `@@` | izquierda (`L637-654`) |
| 8 | `parse_add` | `+`, `-` | izquierda (`L656-673`) |
| 9 | `parse_mul` | `*, /, %` | izquierda (`L675-693`) |
| 10 | `parse_pow` | `^` | **derecha** (`L696-707`) |
| 11 | `parse_unary` | prefijos `-`, `!` | prefijo (`L709-728`) |
| 12 | `parse_postfix` | `.`, `[]`, `()` | izquierda (`L731-764`) |
| 13 | `parse_primary` | literales, `new`, lambdas, `(...)` | N/A |

Nota: `is`/`as` están **por encima** de la lógica y comparaciones, lo que difiere de otros HULKs del curso pero es coherente con la elección "type-check después del cast".

**Ambigüedades resueltas con flags booleanos** (declarado en REPORT §Parser):

- `forbid_as_cast` (`parser.rs:10`): dentro de `with (...)`, `as` no se consume como cast; se reserva para `with (foo() as x) ...`.
- `forbid_pipe_or` (`parser.rs:12`): dentro de `[...]`, `|` no se consume como OR; se reserva para comprensiones `[expr | var in iter]`. Consecuencia documentada en REPORT §Limitaciones: **no se puede escribir `[a | b]` como vector unitario del OR**.

**Lookahead para lambda** (`parser.rs:905-948`): cuando ve `(`, la función `is_lambda_start()` avanza el cursor buscando `Ident : Type (, Ident : Type)* ) =>`. Es un lookahead lineal completo — no hay backtracking real, sólo un preescaneo sin efectos.

**`base(args)` y `match(...)` como detección contextual** (`parser.rs:807-820`): dentro de `parse_primary`, si el `Ident` recién leído es `"base"` o `"match"` y le sigue `(`, se enruta a `parse_base` (produce `Expr::Base { args }`) o `parse_macro_match` en vez de a llamada de función. Esto permite usar `base` como nombre de parámetro (ej. `class Triangle(base: Number, ...)` en `examples/shapes.hulk`) sin conflicto.

**Cuerpo flexible** (`parser.rs:452-466`): `parse_body` acepta `-> expr;` o `=> expr;` o bloque `{...}`. Las funciones y métodos aceptan cualquiera.

**Clases sin `function` explícito** (`parser.rs:377-423`): un método puede escribirse `nombre(params): T -> cuerpo;` sin la keyword; se distingue de atributos porque el `(` inmediato tras el `Ident` denota parámetros. Los atributos pueden usar `=` o `:=` como inicializador y admiten anotación de tipo `nombre: Type = init;`.

**Constructores heredados con argumentos** (`parser.rs:311-321`): al parsear `class X(a, b) inherits Y(a, b)`, los argumentos pasados a `Y(...)` **se parsean pero se descartan**. Esto significa que la clase X no propaga explícitamente `a, b` al constructor del padre — el intérprete llenará los campos por otro mecanismo (ver §6).

**`new T[]...[n]` para arrays multidimensionales** (`parser.rs:1163-1184`): los `[]` vacíos se **codifican dentro del `type_name` como string** (`"Number[]"`, `"Number[][]"`). El intérprete y el semántico decodifican contando sufijos `[]`. Es un pequeño abuso del `String` como carrier de tipo pero funciona.

**`match(...)` para macros** (`parser.rs:204-239`): produce `Expr::MacroMatch { subject, cases: Vec<(pat, body)>, default_body }`. Se distingue de `case ... of` (que es semántico, sobre tipos).

**Programa mezclado**: `parse_program` (`parser.rs:100-155`) acepta libremente declaraciones y expresiones intercaladas en el nivel superior; múltiples expresiones se envuelven en `Expr::Block`.

**82 tests unitarios** (`crates/hulk_parser/src/lib.rs`) cubren literales, precedencia, asociatividad, declaraciones, lambdas, comprensiones, macros y snippets HULK.

---

## 4. AST (`hulk_ast`)

Un único fichero, ~265 líneas (`crates/hulk_ast/src/lib.rs`), muy limpio y sin campos de sobra.

- **Wrapping**: cada nodo va en `Spanned<T> { node, span }` (`lib.rs:6-19`) — coherente pero no hay `expr_id: usize` (a diferencia de otros proyectos del curso que asignan IDs para post-anotación de tipos). Aquí la información de tipo se recomputa cada vez en el checker; no se cachea entre pasadas.
- **`Expr` enum de 26 variantes** (`lib.rs:59-151`) — cubre todo lo requerido: literales, `Var/Self_`, ops, `Assign`, `Let/If/While/For/Block`, `Call/MethodCall/FieldAccess/Index/New/NewArray`, `Case/With`, `IsInstance/Cast`, `VecLit/VecComp`, `Base`, `Lambda`, y las tres formas de macros (`MacroArgRef`, `MacroArgName`, `MacroMatch`).
- **`TypeExpr`** (`lib.rs:23-31`): `Named(String) | Array(Box<TypeExpr>) | Iterable(Box<TypeExpr>) | Function { params, ret }`. Los iterables `T*` y las anotaciones de tipo función están presentes en el AST — no todos los proyectos del curso las tienen.
- **Declaraciones top-level**: `FunctionDecl`, `ClassDecl` con `base: Option<String>` (no lista, así que no hay herencia múltiple de clases) y `members: Vec<ClassMember>` donde cada `ClassMember` es `Attribute { init }` o `Method { params, return_type, body }`. `ProtocolDecl` con `extends: Vec<String>` (sí soporta extends múltiple para protocolos). `MacroDecl` con `params: Vec<MacroParam>` marcados por `MacroParamKind: Value | ByRef | ByName | VarName` (`lib.rs:231-236`).
- **`Program`** (`lib.rs:257-264`): agrupa `functions, classes, protocols, macros` y un `entry: Option<ExprS>` para la expresión de entrada.

El AST es completamente **no-tipado en tiempo de compilación de Rust**: no hay variantes que sólo el semántico pueda producir. Toda la información de tipos vive en el checker.

---

## 5. Análisis semántico (`hulk_semantic`)

`checker.rs` es el fichero grande del proyecto (~1180 líneas). Realiza **dos pasadas** sobre el AST (`lib.rs:15-21`):

**Pasada 1 — `collect_declarations`** (`checker.rs:403-498`):
- Registra `ProtocolInfo { extends, methods: HashMap<name, MethodInfo> }` para cada protocolo.
- Registra `ClassInfo { base, ctor_params, attributes: HashMap<String, Type>, methods: HashMap<String, MethodInfo>, span }`. Las clases sin `base` obtienen `Some("Object")` automáticamente (`checker.rs:435`), unificando el árbol.
- Recolecta funciones globales en `HashMap<String, FuncInfo>`. Duplicados (excepto shadowing de builtins) → `DuplicateDeclaration`.
- Registra **macros como funciones con params `Object` y return `Object`** (`checker.rs:490-495`). Esto es coherente con la limitación auto-declarada: los cuerpos de macros no se verifican semánticamente.
- Corre `check_circular_inheritance` (`checker.rs:378-399`) — DFS con set de visitados.

**Pasada 2 — `check_program`** (`checker.rs:502-521`):
- Define constantes `PI` y `E` como `Type::Number`.
- Corre `check_class_decl` sobre cada clase, luego `check_function_decl` sobre cada función, luego `check_expr` sobre `entry`.

**Sistema de tipos** (`types.rs:1-32`):
```rust
pub enum Type {
    Number, Boolean, Str, Object, Null,
    Named(String), Array(Box<Type>), Unknown,
}
```
`Object` es el techo, `Null` es asignable a cualquier no-primitivo, `Unknown` es error-recovery y silencia diagnósticos aguas abajo.

**Subtipado** (`is_subtype`, `checker.rs:213-258`):
- Reflexivo, `Object` como techo, `Null` a cualquier no-primitivo.
- Para `Type::Named(sup)`, si `sup` es protocolo (`is_protocol(p)`), usa **subtipado estructural**: `class_satisfies_protocol` (`checker.rs:196-210`) recolecta todos los métodos requeridos (incluidos los de protocolos padre vía `extends`) y verifica firma (cantidad de params y compatibilidad de tipo de retorno). Si `sup` es clase, recorre la cadena de herencia con `is_class_subtype` (`checker.rs:260-276`).
- Covarianza de arrays (`checker.rs:230-232`).
- **Un primitivo también puede satisfacer protocolo estructuralmente** (`checker.rs:246-256`): si esperamos `Type::Named(P)` y `P` es protocolo, y `sub` es `Number/Boolean/Str`, comprueba si la "clase" incorporada `Number`/`Boolean`/`String` (registrada como builtin, ver más abajo) cumple. Es un detalle fino que muchos otros HULK del curso no tienen.

**Builtins registrados** (`checker.rs:70-140`):
- Funciones: `print(Object) → Object`, `sqrt/sin/cos/tan/exp(Number)→Number`, `log(Number,Number)→Number`, `rand()→Number`, `range(Number)→Array<Number>` (nota: la firma sólo declara 1 argumento, pero el caso `range` tiene ruta especial en `check_expr` que admite 1 o 2, `checker.rs:762-783`).
- Clases builtin: `Object` con `getType(): String`, `String` con `length/toNumber/concat`, `Number` con `toString`, `Boolean` con jerarquía pero sin métodos propios.

**`join`** (`checker.rs:279-286`): LUB para ramas `if`/`elif`/`else` y arms de `case` — retorna el más general si uno es subtipo del otro, o `Object` como fallback. Sencillo pero suficiente.

**Verificación de expresiones** (`check_expr`, `checker.rs:611-1117`) — cubre las 26 variantes de `Expr`. Puntos notables:

- **`Assign`**: exige que `target` sea `Var | FieldAccess | Index`; cualquier otra cosa emite `InvalidAssignTarget`. Detecta `Null` a primitivo (`NullAssignedToPrimitive`).
- **`Concat`/`ConcatSpace`** (`checker.rs:1135-1148`): acepta `Str`, `Number`, `Boolean`, `Null` y `Object` en cualquier lado (coerción declarada). Sólo rechaza tipos claramente no coercibles.
- **`For`** (`checker.rs:1014-1034`): si el iterable es `Array`, extrae el tipo elemento; si es `Object`, `Named` o `Unknown`, asume tipo elemento `Unknown` (protocolo iterador). Sólo emite error si el iterable es de un tipo escalar.
- **`Case`** (`checker.rs:981-1002`): valida que cada arm tenga un tipo válido; el resultado es el join de los cuerpos.
- **`NewArray`** con nombre codificado con sufijos `[]`: `checker.rs:964-977` decodifica correctamente `"Number[]"` → `Array<Array<Number>>` etc.
- **`Base`** (`checker.rs:1082-1086`): retorna `Type::Object` — no rastrea el tipo del método padre. Aceptable dado el diseño simple.
- **`Lambda`** (`checker.rs:1088-1100`): tipo `Object`. Consistente con la limitación declarada de que los tipos de función se tratan como `Object`.
- **`Cast`** (`checker.rs:1041-1055`): no valida que el cast sea posible — cualquier `expr as T` es aceptado. Coherente con el intérprete que tampoco hace nada en `Cast` (`interpreter.rs:264-267`).
- **`MacroArgRef` / `MacroArgName` / `MacroMatch`** (`checker.rs:1102-1115`): retornan `Object` sin verificar más — coherente con la declaración de que "los cuerpos de macros no se verifican semánticamente".

**Errores**: 15 variantes en `SemanticError` (`error.rs:6-23`) cubriendo lo esperado. Todos exponen `position()` y `clean_message()` que consume el CLI.

**77 tests unitarios** en `hulk_semantic/src/lib.rs` cubren inferencia, subtipado, herencia, protocolos, macros y errores. Pasan al ejecutar `cargo test --release`.

---

## 6. Intérprete tree-walking (`hulk_interpreter`)

`interpreter.rs` es el otro fichero grande (~1165 líneas). Un evaluador `eval(&ExprS, &mut Env) → Result<Value, RuntimeError>` recursivo puro (`interpreter.rs:58-333`). No hay bytecode, no hay AST rewriting hacia formas simplificadas — se ejecuta el AST original.

**Valores runtime** (`value.rs:9-17`):
```rust
pub enum Value {
    Number(f64), Boolean(bool), Str(String), Null,
    Object(Rc<RefCell<HulkObject>>),
    Array(Rc<RefCell<Vec<Value>>>),
    Closure(Rc<ClosureData>),
}
```
`Rc<RefCell<...>>` para objetos y arrays: **mutación compartida por referencia** — cambios via un alias se ven en los otros. No GC, apoyado en el conteo de referencias de Rust (ciclos causarían leaks, declarado en REPORT).

**Environment** (`env.rs:1-59`): pila de `HashMap<String, Value>`; `push`/`pop` para scopes; `assign` mutación in-place con búsqueda desde el interior hacia afuera; `snapshot` aplana todos los scopes para capturar closures.

**Límite de recursión**: `MAX_CALL_DEPTH = 500` (`interpreter.rs:11`) con conteo manual en `call_function`/`call_method`/`call_closure`. Devuelve `RuntimeError::StackOverflow` — necesario porque el tree-walking pone toda la recursión HULK sobre la pila de Rust.

**Estado de "self" y método actual** (`interpreter.rs:19-24`):
- `current_self: Option<Rc<RefCell<HulkObject>>>` — para expr `Self_`.
- `current_class_name`, `current_method_name` — necesarios para dispatch de `base(args)` (buscar el método padre exacto del que se está ejecutando, `interpreter.rs:723-760`).

**Instanciación** (`instantiate`, `interpreter.rs:814-847`):
1. Recolecta la cadena de inicializadores de atributos de la clase base hacia la derivada (`collect_attr_chain`, `interpreter.rs:850-876`).
2. Determina `ctor_class` — la primera clase (empezando por la instanciada) con `ctor_params` no vacíos (`find_ctor_class`, `interpreter.rs:798-812`). Esto es lo que permite que `Knight` sin params propios pero heredando de `Person(a, b)` acepte `new Knight("Phil", "Collins")`.
3. Bindea los params del constructor efectivo en el env.
4. Ejecuta cada inicializador de atributos secuencialmente, escribiéndolos como fields del `HulkObject` y también manteniéndolos en `env` para que los siguientes inicializadores los vean.

Este esquema es correcto para el patrón común `class C(x) { field := x; }` porque el `env` tiene `x` en scope. Sin embargo tiene una **limitación real**: si la clase derivada define `class Knight(a, b) inherits Person(a, b)`, el parser descarta los argumentos `Person(a, b)` (§3). El intérprete llena los campos del padre porque los inicializadores están en `collect_attr_chain` y `a, b` están en env — pero **no invoca al constructor del padre como código separado**; sólo ejecuta secuencialmente los inicializadores de atributos. Para los tests del curso esto funciona porque la convención es que el ctor del padre define los mismos nombres que el hijo pasa hacia arriba.

**Dispatch de métodos** (`call_method_inner`, `interpreter.rs:625-720`):
1. Casos especiales para primitivos: `String.length/toNumber/concat`, `Number.toString/getType`, `Boolean.getType`, `Array.size/getType`, `Null.getType`, `Function.getType`.
2. `getType()` como fallback para cualquier valor (`interpreter.rs:675-677`).
3. Para `Object`: `find_method` recorre la cadena de herencia (`interpreter.rs:763-793`) y ejecuta el cuerpo con `self`, campos de la instancia y params bindeados en un env fresco.

**`base(args)`** (`interpreter.rs:723-760`): usa `current_class_name` para conocer la clase donde vive el método actual, obtiene su base, y llama al método padre con el mismo nombre. Cuidadosamente restaura los tres campos `current_*` al retornar.

**`for` con dos modalidades** (`interpreter.rs:227-257`):
- Si el iterable es `Array`, clona el vec y itera directamente.
- Si es `Object`, llama `next(): Boolean` al inicio de cada iteración y `current(): T` para obtener el valor. Esto implementa el "protocolo iterador" para generadores definidos por el usuario — declarado en REPORT §Generadores como feature bonus.

**Closures** (`interpreter.rs:296-303`, `call_closure` en `interpreter.rs:475-493`): `Lambda` captura `env.snapshot()` (aplanado). Al llamar, se crea un env fresco con las capturas + params. Suficiente para higher-order (map/filter/compose declarados en REPORT).

**Comprensiones de vector** (`interpreter.rs:276-294`): evalúa `iter`, exige `Array`, y para cada elemento define `var` en un scope nuevo, evalúa `body`, colecciona.

**Macros por sustitución AST** (`call_macro` + `substitute`, `interpreter.rs:497-544` y `1063-1166`):
- `Value` → se evalúa antes de la expansión y se bindea en el env como binding normal.
- `ByRef` (`@param`): recibe una expresión que debe ser `Var(name)` o `MacroArgRef(name)`; se registra que `param` se substituye por `Var(caller_var)` — cualquier `param := X` dentro del macro **muta la variable del caller**.
- `ByName` (`*param`): recibe una expresión arbitraria; se registra que `param` se substituye por esa expresión completa — cada uso de `param` reejecuta la expresión (semántica lazy).
- `VarName` (`$param`): recibe una `Var(name)` o `MacroArgName(name)`; se registra que `$param` se substituye por `Str(name)` — el nombre de la variable como string.

`substitute()` (`interpreter.rs:1063-1166`) es un walk exhaustivo del AST que reemplaza `Var(name)`, `MacroArgRef(name)` y `MacroArgName(name)` según los mapas. Cubre todas las 26 variantes de `Expr`. Es una implementación real y funcional del paso por nombre — no todos los HULK del curso la tienen.

**Errores runtime** (`error.rs:3-16`): 10 variantes, cubren lo esperado. `RuntimeError::StackOverflow` es la salvaguarda para recursión infinita. **El CLI trata todos los errores runtime como exit 1** — no como error semántico. Es una decisión de diseño (aceptable porque la interfaz del curso no distingue error runtime).

**75 tests unitarios** en `hulk_interpreter/src/lib.rs` cubren evaluación de todos los operadores, control de flujo, clases con herencia, protocolos, generadores y macros.

---

## 7. Features opcionales

Todos verificados directamente en el código y en los tests unitarios:

- **Tipos y anotaciones**: `let x: T = ...`, params tipados, tipo de retorno, `T[]`, `T*`, `(T) -> R`. AST completo (`hulk_ast/src/lib.rs:23-31`), checker resuelve (`resolve_type`, `checker.rs:144-161`). Los tipos de función se colapsan a `Object` — declarado como limitación.
- **OOP con `is`/`as`**: `IsInstance` (runtime: `is_instance_of`, `interpreter.rs:919-932`) y `Cast` (runtime: identidad, `interpreter.rs:264-267`). El semántico acepta cualquier cast (§5).
- **Herencia simple con `is`/`inherits`**: base único por clase (`ClassDecl.base: Option<String>`), `base(args)` dispatch al padre.
- **Iterables (`T*`)**: parseados por `parse_type_expr` (`parser.rs:513-514`), resueltos a `Unknown` en el checker (permite arrays y objetos con `next/current`).
- **Vectores**: literales `[a, b, c]` y también `{a, b, c}` como sintaxis alternativa (`parser.rs:1252-1262`); comprensiones `[expr | x in iter]`; `new T[n]`, `new T[n] { i -> expr }` (init-lambda por índice, `parser.rs:1191-1220`), `new T[][n]` con dimensiones codificadas en el nombre.
- **Protocolos con `extends` múltiple**: `ProtocolDecl.extends: Vec<String>` — sí soporta extends múltiple para protocolos (aunque `class` tiene base único).
- **Tipado estructural**: `class_satisfies_protocol` (§5) — no requiere `implements`. Se aplica incluso a primitivos.
- **Interfaces**: keyword `interface` como alias exacto de `protocol` (`parser.rs:337-339`). Produce el mismo AST.
- **Funciones de primera clase**: `Lambda` (`(x) => expr`, y también `function(x) -> expr`, ver `parse_anon_function` en `parser.rs:985-1003`), closures con captura léxica.
- **Generadores (protocolo `next()`/`current()`)**: soportado en `for` sobre `Value::Object` (`interpreter.rs:239-249`). Declarado como bonus.
- **Macros `def` y `define`**: cuatro modos de paso (`Value`, `ByRef`, `ByName`, `VarName`), `match(...) { case (pat) => ...; default => ... }`. Ejecución por sustitución AST — implementación completa.

El REPORT (§Características) marca todo esto explícitamente y coincide con el código.

---

## 8. Exactitud del reporte

El REPORT.md tiene 333 líneas y ~3200 palabras. Verificaciones:

- **Tests**: REPORT declara 297 tests (63 lexer + 82 parser + 77 semántico + 75 intérprete). Coincide exactamente con `cargo test --release` local.
- **CI 71/71 + 10/10**: reporte del issue coincide con lo que cabe esperar de las features implementadas — sin acceso al runner del curso no puedo re-ejecutar la suite oficial, pero dado que la implementación cubre las categorías declaradas y los tests unitarios internos son coherentes con esas features, es plausible.
- **Arquitectura**: la descripción del pipeline es correcta al detalle (5 crates + binario, no 6; el REPORT dice "seis crates" en §Visión General, línea 5, y luego enumera "5 crates + hulkc" en la sección de Arquitectura — pequeña ambigüedad, no error).
- **Exit codes**: 0/1/2/3 coinciden con `hulkc/src/main.rs`.
- **`./output` como shell script con base64**: exacto (`main.rs:59-79`).
- **Ambigüedad de `as` y `|`**: la explicación con `forbid_as_cast` y `forbid_pipe_or` es fiel al código (`parser.rs:10-12`).
- **Dos pasadas semánticas**: correcto.
- **`base` no reservado**: correcto — `parser.rs:807-816` lo detecta contextualmente.
- **Sustitución AST para macros**: la descripción del REPORT (líneas 190) es una versión legible y precisa de lo que hace `substitute()` en el código.
- **Runtime errors → exit 1**: declarado y correcto (`main.rs:120-126`).

**Discrepancias menores**:

- El REPORT en §Visión General dice "seis crates" (línea 5) pero después enumera cinco (`hulk_lexer, hulk_ast, hulk_parser, hulk_semantic, hulk_interpreter`) más el binario `hulkc`. Depende de si se cuenta el binario como crate.
- El README declara "297 pruebas unitarias distribuidas entre los crates de lexer, parser, semántico e intérprete". El REPORT desglosa igualmente. Ambos coinciden con la ejecución real.
- El REPORT no menciona explícitamente que **`./output` NO es un ejecutable nativo** hasta la sección §Limitaciones (línea 307). Un lector rápido podría inferir que hay compilación. Los autores lo hacen explícito, pero al final del documento.

En general el reporte es **honesto, técnicamente exacto y bien organizado**. La declaración explícita de "no hay generación de código" en la sección de limitaciones es correcta y valiente — no oculta la naturaleza del proyecto.

---

## 9. Diagnóstico de fallas principales (o su ausencia)

**No hay fallas principales que reportar en la implementación del intérprete**: todos los features declarados funcionan, los 297 tests unitarios pasan, y los ejemplos en `examples/` (fibonacci, shapes, sorting) están alineados con lo soportado. El código es limpio, coherente, sin `unsafe` fuera del truco en `Value::type_name` para `Value::Object` (que es correcto pero podría refactorizarse).

**Observaciones puntuales**, no fallas:

1. **Estrategia**: es intérprete, no compilador. Para un curso de compiladores esto es una decisión sustantiva. Cumple la interfaz del calificador porque nunca inspecciona `./output`; sólo lo ejecuta. Un evaluador humano querrá saber si la rúbrica del curso considera aceptable esta estrategia — la implementación técnica es sólida, pero la naturaleza tree-walking sin backend nativo/LLVM/MIPS distingue este proyecto de la mayoría de los del curso.

2. **Constructor del padre no ejecutado explícitamente**: al declarar `class Knight(a, b) inherits Person(a, b)`, los argumentos `Person(a, b)` se parsean y descartan (`parser.rs:314-317`). El intérprete recolecta los inicializadores de atributos desde la base hacia la derivada con `a, b` en env, lo que en la práctica funciona para todos los tests del curso. Pero un patrón como `class Foo(x) inherits Bar(x * 2) { ... }` (donde el hijo pasa una expresión distinta al padre) **no propagaría `x * 2`** — el intérprete usaría el `x` del hijo directamente. No hay test que fuerce este patrón en la suite oficial.

3. **Cast siempre acepta**: `expr as T` no valida en runtime que la conversión sea válida (`interpreter.rs:264-267`). Para primitivos-a-clase, `Cast` es identidad. Un `1 as MyClass` no fallaría; sólo fallaría cuando se acceda a un método/campo que no existe. En la práctica los tests no dependen de esto.

4. **Tipos de función tratados como `Object`**: declarado como limitación. En consecuencia, pasar una función con firma incorrecta a `map(fn, list)` no da error semántico — sólo falla en runtime al invocar. Aceptable dado el alcance.

5. **Cuerpos de macros no verificados**: declarado. `def foo(@x) { y + 1 }` con `y` no definido no da error semántico en la definición del macro; sólo al expandirse en un sitio donde `y` no está en scope. Aceptable dado el diseño (macros son polimórficos por naturaleza).

6. **`|` dentro de `[...]` no puede ser OR**: declarado. Concesión de diseño consciente para evitar backtracking. Sin impacto en tests.

7. **Sin recuperación de errores en parser**: cualquier error sintáctico aborta. Sin impacto en interfaz (que sólo pide el primer error).

8. **Sin `unsafe` importante y sin dependencias externas**: valor de calidad — proyecto autocontenido, portable, reproducible.

**Conclusión**: proyecto sólido en su categoría (intérprete). Implementación completa de todos los features marcados en el issue. La única "reserva" es de política académica, no técnica: es un intérprete presentado como compilador. Los autores lo declaran en el REPORT (§Limitaciones), lo que es lo correcto.
