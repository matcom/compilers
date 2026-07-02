---
student: Alina Maria de la Noval, Fabio Alonso Bañobre, Glenda Natali Rios Rodriguez
issue: 37
repo: GlenRios/HULK_compiler
branch: main
date: 2026-07-02
---

# Evaluación técnica — Compilador HULK del equipo Alina, Fabio & Glenda

## 1. Descripción arquitectónica

El proyecto es un compilador HULK escrito en **Rust 2024** (`Cargo.toml:4`, `edition = "2024"`) que produce ejecutables ELF nativos para Linux x86-64 vía LLVM 17. La topología es un pipeline clásico de 4 fases coordinado desde `src/main.rs:46-120`:

1. **Lexer** (`src/lexer/`) — NFA de Thompson serializado a `bincode` y cacheado en `.hulk_cache/nfa.bin` (`src/main.rs:31-44`).
2. **Parser** (`src/parser/`) — construcción LALR(1) *desde cero*: definición de gramática, cálculo de FIRST/FOLLOW, ítems LR(0), fusión LALR y tabla ACTION/GOTO. Tabla también cacheada (`.hulk_cache/parser.bin`) para amortizar el costo de arranque.
3. **Análisis semántico** (`src/semantic/`) — dos pasadas sobre la lista de declaraciones (colección + tipado con write-back).
4. **Codegen** (`src/codegen/`) — emisión de LLVM IR vía `inkwell 0.4` (LLVM 17), pipeline `mem2reg,instcombine,reassociate,simplifycfg`, y dos modos: JIT (para tests) y AOT (emitir `.o` + linkear con `hulk_runtime.a` usando `gcc`).

Adicionalmente:

- **Runtime en C** (`runtime/hulk_runtime.c`, 141 líneas) — implementa `hulk_print`, `hulk_str_from_number`, `hulk_str_concat[_space]`, `hulk_str_eq`, `hulk_str_size`, `hulk_vec_alloc/get/size`, `hulk_range_alloc/next/current`, `hulk_rand`, `hulk_type_error`. Se compila a `hulk_runtime.a` (`Makefile`).
- **Runtime también en Rust** (`src/codegen/runtime.rs:118-262`) — segunda implementación del mismo contrato con `#[unsafe(no_mangle)] extern "C"`, para que el JIT resuelva las funciones vía `dlsym` desde el propio proceso del compilador (`src/codegen/jit.rs:71-91`). Doble implementación (C para AOT, Rust para JIT) — decisión de diseño interesante.
- **Total de código Rust**: ~6.288 líneas en `src/codegen/` + 2.500 líneas en `src/semantic/` + parser modular + lexer NFA + AST. Muy modularizado.
- **Dependencias**: `inkwell = "0.4"` con feature `llvm17-0`, `llvm-sys = "170"` con `force-dynamic` (justificado en REPORT.md §10: evita ejecutables de 50-200 MB).
- **Contrato de salida**: exit codes 0/1/2/3 para éxito/léxico/sintáctico/semántico, con mensajes `(línea,columna) TIPO: mensaje` a `stderr` (`src/main.rs:73-119`). Cumple la interfaz del CI.

Existe también `docs/REPORT.tex` (versión formal en LaTeX) y `REPORT.md` (2.291 palabras) en el árbol.

## 2. Lexer

Diseño no convencional: el lexer no usa un generador tipo `logos`, tampoco escribe DFAs a mano — construye un **NFA maestro por fusión ε de sub-NFAs**, uno por cada token, mediante la construcción de Thompson.

Componentes:

- `src/lexer/regex_ast.rs`, `src/lexer/regex_parser.rs` — mini-parser recursivo de expresiones regulares (literales, concatenación, unión `|`, `*`, `+`, `?`, `.`, rangos `[a-z]`).
- `src/lexer/thompson.rs` (215 líneas) — construcción de NFA por cada nodo del `RegexAST`: `build_literal`, `build_concat`, `build_union`, `build_star`, `build_plus`, `build_optional`, `build_dot`, `build_range`. Cada regla es fiel a Thompson clásico.
- `src/lexer/master_nfa.rs:17-58` — `MasterNFA::from_token_definitions` toma todas las definiciones y las une con transiciones ε desde un `global_start` común. Guarda por estado de aceptación el `(TokenType, skippable)` y un vector `accept_order` para respetar prioridad al desempatar.
- `src/lexer/master_nfa.rs:117-161` — `match_longest` es una simulación NFA en tiempo de tokenización: mantiene el conjunto de estados actuales, aplica `epsilon_closure` + `move_on_char` en cada símbolo, guarda la última posición aceptante (longitud máxima) y desempata por `accept_order` (prioridad de aparición).
- `src/lexer/token_definition.rs:9-373` — 60+ definiciones de tokens con sus regex y prioridades. El orden es crucial: keywords antes que `IDENTIFIER`, operadores multi-carácter antes que sus prefijos.

Detalles finos:

- **`base` no es keyword** (`token_definition.rs:116-121`, decisión documentada) — se lexea como `IDENTIFIER` y solo obtiene semántica especial en `check_call`/`lower_call` cuando aparece como callee y no hay un local con ese nombre. Solución "soft keyword" limpia.
- **`interface` es alias de `protocol`** (`token_definition.rs:127`) — mismo `KW_PROTOCOL` para ambos.
- **Validación de escapes** (`src/lexer/lexer.rs:54-67, 87-111`) — el regex de `STRING` no valida escapes; se hace post-hoc: `\n`, `\t`, `\"`, `\\` son válidas, cualquier otra produce token `ERROR`. Precisamente reportado como LEXICAL para satisfacer el contrato (exit 1) en vez de degradar a SYNTACTIC.
- **Caché de NFA**: el NFA maestro se serializa con `bincode` a `.hulk_cache/nfa.bin` la primera vez y se deserializa después (`src/main.rs:31-44`) — amortiza los ~200 sub-NFAs entre invocaciones.
- **Debilidad del regex de NUMBER**: `"[0-9]*([.][0-9]+)?"` (`token_definition.rs:55`) — acepta la cadena vacía como número. En la práctica el lexer no la emite porque `match_longest` requiere al menos un carácter aceptante, pero el patrón es teóricamente ambiguo.

## 3. Parser

Uno de los aspectos más ambiciosos del proyecto: **generador LALR(1) escrito a mano en Rust**, sin `LALRPOP`, `pest`, `yacc/bison` ni nada similar.

Estructura (`src/parser/`):

- `grammar/hulk.grammar` (18KB) — documento de referencia de la gramática, no ejecutable, comentado.
- `grammar/hulk_grammar.rs` (27KB) — la misma gramática codificada como `Grammar` con `Production`, `Symbol::T(Terminal)` y `Symbol::NT(NonTerminal)`.
- `lalr/first_follow.rs` (18KB) — cálculo de conjuntos FIRST/FOLLOW por punto fijo.
- `lalr/item.rs` — ítems LR(1) con lookahead + `closure`/`goto`.
- `lalr/automaton.rs` (11KB) — colección canónica de ítems LR(1).
- `lalr/table_builder.rs:22-77` — **fusión LR(1) → LALR(1)**: agrupa estados por *core* (`prod_id`, `dot`) y une los lookaheads. Esto es LALR clásico bien implementado.
- `lalr/parse_table.rs` — `ParseTable { action: HashMap<(state,Terminal),Action>, goto: HashMap<(state,NonTerminal),usize> }` con detección de conflictos.
- `engine/parser.rs:34-126` — bucle shift/reduce/accept clásico. Al reducir, hace pop de `body_len` elementos de la pila, llama a `sem_reduce(prod_id, ...)` para construir el nodo AST, y aplica el GOTO.
- `engine/semantic_actions.rs` (41KB) — el gran despachador: recibe el `prod_id` y los valores de la pila, y construye el nodo AST correspondiente (~380 producciones, cada una con su acción).
- `engine/error.rs` — errores estructurados con `expected: Vec<Terminal>` para mensajes útiles.

Precedencia y asociatividad se codifican en la jerarquía gramatical (`hulk.grammar:159-292`):

```
AssignExpr → OrExpr | OrExpr ':=' AssignExpr | OrExpr '+=' AssignExpr ...
OrExpr → AndExpr | OrExpr '|' AndExpr             (izq)
AndExpr → CompareExpr | AndExpr '&' CompareExpr   (izq)
CompareExpr → IsAsExpr | CompareExpr '==' IsAsExpr ...
IsAsExpr → ConcatExpr | IsAsExpr 'is' TypeName | IsAsExpr 'as' TypeName
ConcatExpr → AddExpr | ConcatExpr '@' AddExpr | ConcatExpr '@@' AddExpr
AddExpr → MulExpr | AddExpr '+' MulExpr | AddExpr '-' MulExpr
MulExpr → PowerExpr | MulExpr '*' PowerExpr ...
PowerExpr → UnaryExpr | UnaryExpr '^' PowerExpr   (der)
UnaryExpr → PostfixExpr | '-' UnaryExpr | '!' UnaryExpr
PostfixExpr → CallOrAccess | CallOrAccess '++' | CallOrAccess '--'
CallOrAccess → PrimaryExpr | CallOrAccess '(' ArgList ')' | ... | '[' Expr ']'
```

Notas:

- **Operadores lógicos son de carácter simple** `|`/`&`, no `||`/`&&` — el lexer sí reconoce `&&`/`||` pero la gramática usa los simples (`token.rs` y `hulk.grammar:196,202`). Divergencia con muchos programas HULK del corpus público que usan `||`/`&&`.
- **`else` es obligatorio en `if`** (`hulk.grammar:326`) — no hay dangling-else, decisión razonable.
- **Vectores como generador** con `[Expr '|' IDENTIFIER 'in' Expr ']` (`hulk.grammar:363`) — conflicto shift/reduce con OR sobre `|` documentado en el propio `grammar` file, resuelto en `table_builder.rs`. **Sin embargo, los tests del corpus usan `[expr || x in it]` con `||`, no `|`** — esto explica varios fallos en `ok/arrays/`.
- **AST**: `src/parser/ast/expr/*.rs`, un archivo por variante (`assign.rs`, `binary.rs`, `block.rs`, `call_access.rs`, `for_expr.rs`, `if_expr.rs`, `let_expr.rs`, `literal.rs`, `new_expr.rs`, `unary.rs`, `vector.rs`, `while_expr.rs`). Todos los nodos llevan `Span` y `id: u32` (para asociar tipo inferido).
- **Sin `Lambda` en el AST** — no existe `lambda_expr.rs` bajo `parser/ast/expr/` y no hay producciones para funciones anónimas en la gramática. `Function` solo aparece como `Decl::Function(FuncDecl)`.
- **Sin `Macro` / `define`** — no hay producciones para `define name(...) -> ...`.

## 4. Análisis semántico

Dos pasadas orquestadas por `TypeChecker::check_program` (`src/semantic/type_checker.rs:96-…`):

**Pasada 1 — `collect_all_declarations`**: registra todos los tipos, protocolos y funciones. Los atributos y parámetros sin anotación reciben `HulkType::Unknown` como placeholder para permitir referencias mutuamente recursivas.

**Pasada 2 — chequeo de cuerpos**: infiere tipos, verifica firmas contra anotaciones, y **escribe de vuelta** los tipos inferidos en `TypeHierarchy` (documentado en `REPORT.md:82-84`). Este write-back es esencial para que codegen tenga tipos concretos.

`HulkType` (`type_system.rs:9-21`): `Number`, `StringT`, `Boolean`, `Null`, `Object`, `Vector(Box<HulkType>)`, `UserDefined(String)`, `Protocol(String)`, `Unknown`, `Never`. `Never` propaga errores sin producir cascadas de falsos positivos (`conforms` retorna `true` en cuanto uno de los operandos es `Never`, `type_system.rs:108-109`).

**Subtipado** (`type_system.rs:107-146`):
- Todo conforma con `Object`.
- Nominal para `UserDefined`.
- Primitivos suben al nombre canónico (`Number` conforma con `UserDefined("Number")`).
- `Null` conforma con `UserDefined` y `Object` (nullable).
- Estructural para protocolos: si `child` es un `UserDefined`, chequea que implemente los métodos del protocolo con covarianza del retorno y contravarianza de parámetros (`type_system.rs:220-243`). Correcto teóricamente.

**Protocolo `Iterable` built-in** (`type_system.rs:391-406`): registrado con `next(): Boolean` y `current(): Object`. `Range` se registra como implementación (`type_system.rs:410-418`).

**LCA** (`type_system.rs:281-300`) — sube desde `b` buscando el primer ancestro compartido con `a`. Usado para tipar `if/elif/else`. Fallback a `Object` si no hay antepasado común.

**Chequeo del `for`** (`type_checker.rs:1267-1308`) — acepta `Vector[T]`, `Range` explícito, o cualquier `UserDefined` que `conforms_protocol(_, "Iterable")`. En el caso Iterable, extrae el tipo del elemento del `return_type` de `current()`. Semánticamente correcto.

**Built-ins** (`type_checker.rs:67-90`): `print`, `sqrt`, `sin`, `cos`, `exp`, `log`, `rand`, `range`. Constantes `PI`, `E`, `true`, `false`. Faltan `size` y `len` como funciones (están como métodos `Vector.size()`).

**Errores acumulados**: todos los `SemanticError` se guardan y se reportan al final (`errors.rs`, `type_checker.rs:33`). Cada uno lleva `Span` — mensajes con línea y columna.

**Bug conocido** — mensaje "Expected type 'Iterable', found 'Iterable'" en el CI: aparece en `generator_squares.hulk` cuando el parámetro se declara `gen: Number*` y se pasa `new Squares(3)`. El chequeo de conformidad rechaza el subtipado porque compara la representación string `Iterable` con `Iterable`, pero probablemente son objetos distintos (`Protocol("Iterable")` vs `UserDefined(...)` con protocolo sintetizado). No hay soporte real para el sufijo `*` en tipos de parámetro — el parser lo consume (`hulk.grammar:144`, `TypeName → IDENTIFIER '*'`), pero la representación semántica queda ambigua.

## 5. Codegen (inkwell + LLVM 17 + JIT)

`CodegenContext` (`src/codegen/context.rs:16-31`) agrupa `Context`, `Module`, `Builder`, `SymbolTable`, mapa de funciones, jerarquía de tipos, registro de objetos y contexto de método/self actual.

Dos modos (`src/codegen/jit.rs`):

- **`execute_program_jit`** (`jit.rs:48-99`) — usado en tests. Crea `JitExecutionEngine`, mapea las funciones `hulk_*` del proceso Rust (dlsym) y ejecuta `__hulk_entry() -> f64`.
- **`compile_to_binary`** (`jit.rs:111-162`) — usado en producción. Añade `main()` que llama a `__hulk_entry` y retorna 0, escribe `.o` a `/tmp/hulk_program.o` con `TargetMachine::write_to_file`, y llama a `gcc /tmp/hulk_program.o hulk_runtime.a -o output -no-pie -lm`.

**Layout de objetos** (`src/codegen/objects.rs`, `lower_program.rs:117-166`):

- Cada tipo tiene `struct { i32 type_tag, ptr vtable_ptr, campo0, campo1, ... }` con los campos del padre primero (`collect_field_names`, `lower_program.rs:190-207`).
- `type_tag` se asigna en **DFS pre-orden** del árbol de herencia (`lower_program.rs:211-225`), garantizando que todos los subtipos de un tipo `T` reciban tags contiguos en `[T.min_tag, T.max_tag]`. Permite que el chequeo `is` sea una comparación de rango (`lower_expr/collections.rs:30-59`). **Excelente decisión de diseño.**
- Vtables como structs globales con un puntero a función por método (`objects.rs:5-15`, `lower_decl.rs:208-231`). El slot de cada método es su índice en `method_names` construido por herencia (padre primero, override reemplaza el mismo slot).
- Vtables se llenan en `init_vtable_global` después de emitir todos los métodos porque se necesitan sus `FunctionValue`s.

**Despacho** (`src/codegen/dispatch.rs`):

- **Estático** (`method_dispatch`, `dispatch.rs:41-89`): resuelve el nombre canónico `__hulk_method_<Type>_<method>` usando `find_method_impl_type` — sube la cadena de herencia hasta encontrar quién implementa. Se emite `build_call` directo si el receptor es de tipo concreto.
- **Dinámico por vtable** (mismo `method_dispatch`): carga el `vtable_ptr` del campo 1, GEP al slot del método, load del `fn_ptr`, y llamada indirecta. Un solo load + call.
- **Dinámico por protocolo** (`method_dispatch_protocol`, `dispatch.rs:94-207`): carga `type_tag`, emite un `build_switch` con un case por cada tipo conformante registrado en `protocol_conformers`, y en cada case emite el call estático a `__hulk_method_<impl>_<method>`. Después, un PHI en el merge block unifica los resultados. Es correcto y bastante elegante — aunque hincha el IR si hay muchos conformantes.

**Coerciones y valores** (`src/codegen/value.rs`, `coerce.rs`):

- `CgValue` enum: `Number(FloatValue)`, `Bool(IntValue)`, `Str(PointerValue)`, `Object(PointerValue)`, `Vector(PointerValue)`, `Null`, `Void`.
- `coerce_arg` (`coerce.rs`) hace las conversiones necesarias para pasar argumentos: `Number` → `Number` directo, `Number` → `Object` a través de `hulk_str_from_number` (boxing débil), etc.

**Lowering de expresiones** (`src/codegen/lower_expr/mod.rs` y sub-módulos):

- **`Let`** (`mod.rs:199-212`): abre scope, evalúa binding, `create_entry_alloca_for` con el tipo semántico, `store_place`, evalúa body.
- **`If`** (`control_flow.rs:14-124`): estructura clásica con `then_block`, `elif_i_cond`/`elif_i_then` para cada elif, `if_else`, `if_merge`. PHI en el merge con inferencia del tipo desde el primer `incoming`. **Limitación**: si los tipos de las ramas no coinciden exactamente (por ejemplo, si mezcla `Str` y `Object`), promueve a `Object` pero puede perder la etiqueta correcta.
- **`For`** (`control_flow.rs:126-248`) — **aquí está el bug de generators**: la lógica solo distingue dos casos (`is_range` para `UserDefined("Range")`, y "es un vector") y llama a `hulk_range_next`/`hulk_range_current` o `hulk_vec_get`/`hulk_vec_size` respectivamente. Un `UserDefined` que implemente `Iterable` (como `Countdown`, `MyRange`, `Squares`, etc.) cae en el else y se trata como vector — llama `hulk_vec_size` sobre un objeto arbitrario y lee basura como tamaño. Debería, en su lugar, invocar `obj.next()` / `obj.current()` vía vtable.
- **`Call`** (`calls.rs:12-…`): trata `base` como soft keyword y hace la llamada directa al método del padre. Trata `print` como especial: si el argumento es `Object`, imprime `<TipoNominal>` en vez del contenido real — no invoca `toString()` sobrescrito (documentado en `REPORT.md:241`).
- **`Vector`** (`collections.rs:64-…`): `hulk_vec_alloc(n, ELEM_SIZE_BYTES=8)` + un `hulk_vec_get` por elemento para escribirlos in-place. Soporta literal `[a,b,c]` y generador `[expr | x in iterable]`.
- **`Is` / `As`** (`collections.rs:13-62`, `mod.rs:283-337`): ambos usan el rango DFS de tags. `as` con fallo llama a `hulk_type_error` (unreachable después).

**Verificación**: al final de `visit_program` (`lower_program.rs:59-61`) y de nuevo en `compile_to_binary` (`jit.rs:135-137`) se llama a `module.verify()`. En la primera CI de este equipo, aparecía "invalid InstCombine" — corregido añadiendo `mem2reg` antes de `instcombine` (`jit.rs:25`, pipeline `mem2reg,instcombine,reassociate,simplifycfg`).

**JIT**: `add_global_mapping` para cada `hulk_*` (`jit.rs:71-91`) permite que el JIT resuelva las funciones sin depender de dlopen. Interesante: usa la implementación Rust del runtime, no la C.

## 6. Runtime (C)

`runtime/hulk_runtime.c` (141 líneas) implementa el mismo contrato que `codegen/runtime.rs`, para el modo AOT:

- **Strings**: `hulk_print` con `puts("null")` para null-pointer; `hulk_str_from_number` con `snprintf("%lld")` para enteros y `"%g"` para decimales (con umbral `fabs(n) < 1e15`); `hulk_str_concat[_space]` con `malloc` + `memcpy`; `hulk_str_eq` con `strcmp`.
- **Vectores**: layout `[int64 count][8 bytes elem_0]...`. `hulk_vec_alloc` usa `calloc`; `hulk_vec_get` valida el índice y aborta con `fprintf(stderr) + abort()` en overflow — correcto y ruidoso.
- **Range**: layout `[f64 start][f64 end][f64 current]` con `current = start - 1` para que el primer `next()` lo lleve a `start`.
- **Sin GC**: memoria se pierde después de cada asignación. Documentado en `REPORT.md:242` como limitación.

Correspondencia 1:1 con las declaraciones `declare_extern` de `codegen/runtime.rs:36-102`, así que el módulo LLVM emite las mismas llamadas y el linker C las resuelve.

## 7. Features opcionales

Contra las casillas marcadas en el issue #37:

| Feature | Declarado | Implementado | Evidencia |
|---------|-----------|--------------|-----------|
| Minimal (expresiones, funciones, variables, condicionales, ciclos) | ✅ | ✅ | 20/20 en `ok/minimal` |
| Sistema de tipos con inferencia | ✅ | ✅ | Two-pass con write-back (`type_checker.rs`), 10/10 en `ok/types` |
| OOP: herencia, polimorfismo, `is`/`as` | ✅ | ✅ | Vtables, tags DFS, 10/10 en `ok/oop` |
| Iterables / `for` | ✅ | ⚠ Parcial | Solo `Range` y `Vector` en codegen (`control_flow.rs:135-150`). User-defined iterables definidos con `next/current` pasan semántico pero fallan en ejecución. 0/6 en `ok/generators`. |
| Vectores / arrays | ✅ | ⚠ Parcial | Literal `[a,b,c]` + generador `[e \| x in it]` funcionan; `new Number[n]` y literal `{a,b,c}` (curly) no. 0/8 en `ok/arrays`. |
| Protocolos | ✅ | ✅ | Estructural con covarianza/contravarianza, despacho por vtable. 10/10 en `ok/interfaces`. |
| Functors (first-class fns) | ❌ | ❌ | Consistente: no hay AST node ni gramática. 0/7 en `ok/lambdas`. |
| Macros | ❌ | ❌ | Consistente: no hay `define` en el lexer. 0/8 en `ok/macros`. |

Sobre los **extras** (10/10): incluye `for`/`while`, `range()`, `for anidados`, `for` complejo con `let`. Todos con `Range` — que sí funciona.

Correcto que functors y macros no estén marcadas — la implementación es honesta.

## 8. Exactitud del reporte

`REPORT.md` (2.291 palabras, 11 secciones) es de alta calidad, técnicamente preciso, y en general fiel al código:

**Correctamente descrito**:

- Lexer NFA / Thompson (§2, con detalle del `MasterNFA` y su fusión). ✓
- LALR(1) desde cero (§3, con la jerarquía de precedencia exacta). ✓
- Two-pass con write-back en semántica (§4.1). ✓
- Layout de objetos con `type_tag` DFS + vtable (§5.3). ✓
- Runtime dual (C + Rust) (§6, aunque solo menciona explícitamente el C — hay que buscar en `runtime.rs` la contraparte Rust). ✓
- Pipeline AOT: LLVM IR → `.o` → gcc → ELF (§7). ✓
- Optimización `mem2reg,reassociate,simplifycfg` (§5.5). **Discrepancia menor**: el código real usa `mem2reg,instcombine,reassociate,simplifycfg` (`jit.rs:25`) — añade `instcombine`, no listado en el README.

**Limitaciones honestamente reconocidas** (§9):

- Lambdas no soportadas. ✓
- Escapes de string no procesadas — **inexacto**: sí se validan como error léxico si son inválidas (`lexer.rs:87-111`) y sí se procesan `\n \t \" \\` (mencionado en el lexer y en `semantic_actions.rs`, aunque no verifiqué la ejecución).
- `toString()` fallback. ✓ (`calls.rs:106-114` imprime `<TipoNominal>`).
- Sin GC. ✓
- Parser sin recuperación de errores. ✓
- Aritmética solo `f64`. ✓

**Discrepancias / omisiones**:

- El reporte dice "384 tests pasan" (§11). En este audit no ejecuté `cargo test`, pero por la cantidad de módulos de test (`src/codegen/tests.rs` = 1.249 líneas, `src/semantic/tests.rs` = 68KB, `src/parser/tests/*` = 51KB), es plausible.
- **No menciona el fallo de user-defined iterables**: el reporte lista "Iterable/Range" como implementado en §8 pero no aclara que solo `Range` funciona en codegen. Con el fallo del CI a la vista, el reporte debería haber mencionado esta limitación.
- **No documenta el bug de `Number*`**: el tipo iterable como parámetro está en la gramática (`TypeName → IDENTIFIER '*'`) pero produce el error "Expected 'Iterable', found 'Iterable'" en la semántica.

En términos de comunicación técnica: excelente. Detalles como el DFS pre-order para `is`, la razón para linkeo dinámico de LLVM, la coexistencia de runtime C+Rust, la elección de LALR desde cero — todas justificadas con criterio.

## 9. Diagnóstico de fallas principales

Distribución de fallos observados:

**A. Iterables definidos por el usuario (0/6 en `ok/generators`)** — la falla más importante:

El corpus incluye seis programas con tipos como `Countdown`, `MyRange`, `Evens`, `Odds`, `Squares` que definen `next(): Boolean` y `current(): Number` — implementan estructuralmente el protocolo `Iterable`. Semánticamente se validan (`type_checker.rs:1277-1290` acepta `conforms_protocol(n, "Iterable")`), pero el codegen (`control_flow.rs:126-248`) solo distingue dos casos:

```rust
let is_range = matches!(&iter_ty, HulkType::UserDefined(n) if n == "Range");
// ...
if is_range {
    // hulk_range_next / hulk_range_current
} else {
    // hulk_vec_size / hulk_vec_get   <-- BUG: se ejecuta para user-defined Iterable
}
```

Un `UserDefined("Countdown")` cae en el else y se pasa a `hulk_vec_size` que lee los primeros 8 bytes como `int64`. Como el primer campo del struct es `i32 type_tag`, se lee un tamaño gigante y garbage — el bucle nunca ejecuta el cuerpo o se cuelga. Los tests fallan con salida `fail` (predicado de la comprobación al final).

**Fix conceptual**: cuando `iter_ty` es `UserDefined` no-Range y conforma con `Iterable`, emitir `while (obj.next()) { let x = obj.current() in body }` usando `method_dispatch` para las dos llamadas. Es un caso más en el `match` de `lower_for`.

**B. `generator_squares` — semántico**: `Expected type 'Iterable', found 'Iterable'`

El parámetro se declara `gen: Number*`. La gramática acepta `TypeName → IDENTIFIER '*'` (`hulk.grammar:144`), y probablemente `TypeName::Iterable { .. }` en el AST (`type_checker.rs:1436`). La conversión a `HulkType` produce `HulkType::Protocol("Iterable")`, pero probablemente sin registrar el elemento. Al pasar `new Squares(3)`, el chequeo compara la representación con la anotación y produce el mensaje literal. Bug de nombrado inconsistente entre AST y `HulkType`.

**C. Lambdas / functors (0/7 en `ok/lambdas`)**: no implementadas por diseño. Ejemplo del corpus:

```
let f: (Number) -> Number = function (x: Number): Number -> x * 2 in { ... }
```

Falta: la sintaxis de tipos de función `(T) -> R`, la expresión `function(...) -> expr` como valor de primera clase, y closures capturando el entorno. Ninguna pieza está presente. El fallo del parser es `SYNTACTIC: token inesperado '(', se esperaba: IDENTIFIER` (a la altura del `(` tras `function`, porque su gramática exige `IDENTIFIER` — solo permiten `function nombre(...)`).

**D. Macros (0/8 en `ok/macros`)**: no implementadas por diseño. Falta la producción `Decl → 'define' IDENTIFIER '(' Params ')' ':' Type '->' Expr ';'`. El fallo del parser es `SYNTACTIC: token inesperado '<nombre>'` con múltiples opciones esperadas — porque el lexer ve `define` como `IDENTIFIER`, el parser espera continuar una expresión y falla al siguiente identificador.

**E. Arrays con sintaxis alternativa (0/8 en `ok/arrays`)**: el corpus usa `new Number[5]` (constructor de array por tamaño) y `{10, 20, 30}` (literal con llaves). Sin embargo, la gramática del equipo solo soporta:
- `[elem0, elem1, ...]` (literales con corchetes).
- `new TypeName(args)` (constructor de tipos, no de vectores).

Fallos típicos: `SYNTACTIC: token inesperado '[' esperaba '='` (para `new Number[5]`), `token inesperado ',' esperaba '; }'` (para `{10, 20, 30}` que se parsea como bloque `{ Expr }`).

**F. Divergencia menor en operadores lógicos**: la gramática usa `|` y `&` para OR/AND, mientras que el corpus público y REPORT.md mencionan `||` y `&&`. El lexer sí reconoce ambos (`OP_OR`/`OP_AND` para `|`/`&`, `OP_INCREMENT` no aplica; `KW_OR`/`KW_AND` no existen), pero la gramática usa los simples. Programas con `&&` pueden fallar el parser (no vi el fallo específico en los logs, pero podría ser fuente de fricción con el corpus canónico si aparece).

Ninguna de las 8 categorías obligatorias (minimal, types, oop, errores léxicos, errores sintácticos, errores semánticos, extras, interfaces) tiene fallos — 71/71 pasan. Los fallos concentran en features **no marcadas** (lambdas, macros) o en un bug específico (user-defined iterables + arrays con sintaxis alternativa).

**Prioridad de fixes**:

1. **User-defined iterables en `for`** (`lower_expr/control_flow.rs`) — 6 tests. Impacto: alto (feature marcada). Esfuerzo: bajo (~30 líneas).
2. **`Number*` en anotaciones** (`type_checker.rs` para `HulkType::Protocol("Iterable")` con parámetro) — 1 test. Impacto: medio. Esfuerzo: medio (requiere protocolo paramétrico).
3. **Arrays sintaxis alternativa** — 8 tests. Impacto: medio (feature marcada, pero corpus usa sintaxis alternativa). Esfuerzo: medio (parser + codegen para `new T[n]`).
4. **Lambdas** — 7 tests. Impacto: bajo (feature NO marcada). Esfuerzo: alto (AST + gramática + closures + tipos función).
5. **Macros** — 8 tests. Impacto: bajo (feature NO marcada). Esfuerzo: alto (fase de expansión pre-parse).

En conjunto, un proyecto muy sólido, con arquitectura elegante y decisiones bien justificadas. El bug de iterables user-defined es el único error de implementación sobre features marcadas — el resto son features opcionales no comprometidas.
