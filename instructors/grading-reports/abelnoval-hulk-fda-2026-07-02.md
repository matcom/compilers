# Reporte Técnico Detallado — Abel de la Noval Pérez, Darian Santamarina Hernández, Frank Alberto Piz Torriente

> Repositorio: https://github.com/ABELNoval/Hulk-FDA
> Rama: develop | Evaluación: 2026-07-02
> Generado por: Claude Code (evaluación automática)

---

## Bloque 1 — Arquitectura

**Lenguaje y herramientas de construcción.** El compilador está escrito en Rust (edition 2024) usando Cargo. Se compone de dos crates: `hulk-compiler` (binario y librería principal en `src/`) y `runtime-rs` (librería estática con ABI C). El backend LLVM se activa vía feature `llvm-verify` con la dependencia `inkwell` versión 0.9.0 y feature `llvm16-0-prefer-dynamic` (`Cargo.toml:L8-14`). El proceso completo es `make build` → `cargo build --release --features llvm-verify` → copia a `./hulk` (`Makefile:L4-6`).

**Estructura general.** El código se organiza en módulos independientes: `lexer/`, `parser/`, `semantic/`, `ir/`, `codegen/`, `pipeline/`, `cli/`, `utils/`, y `execution.rs` (`src/lib.rs`). El `pipeline/` orquesta las fases (`pipeline/mod.rs:L64-146`) con etapas explícitas Lex → Parse → Semantic → Ir → Codegen.

**Lexer.** Es un lexer **hand-written** en `src/lexer/mod.rs` implementado como AFD explícito. El bucle principal está en `next_token` (`lexer/mod.rs:L70-227`) que hace dispatch por primer carácter. Soporta lookahead de un carácter para operadores compuestos (`==`, `!=`, `<=`, `>=`, `:=`, `=>`, `->`, `@@`, `||`) en las líneas `L89-191`. Reconoce comentarios de línea `//` y bloque `/* */` (`lexer/mod.rs:L415-450`); notablemente **no soporta `#`** como comentario.

**Parser.** Es un parser recursive-descent manual en `src/parser/mod.rs` (1817 líneas). Cada nivel de precedencia es una función. La entrada `parse_program` (`parser/mod.rs:L87-142`) permite mezclar declaraciones (`function`, `type`, `protocol`) y una expresión de entrada final. Puede recuperarse parcialmente de errores mediante `synchronize()`.

**AST.** Está en `src/parser/ast.rs`. `Expr` es un struct con `id`, `kind` (`ExprKind`) y `span`; el `id` viene de un contador atómico (`ast.rs:L177-187`). Los `ExprKind` incluyen `Literal, Identifier, Unary, Binary, Block, Call, Assignment, If, While, For, Let, MemberAccess, IndexAccess, TypeCheck, TypeCast, New, Self_, Base, VectorLiteral, VectorComprehension, Lambda` (`ast.rs:L394-488`). No existe nodo `CaseExpr` ni `Define/Macro`. Los tipos se representan con `TypeReference` que puede ser `Named`, `Iterable(T)`, `Vector(T)` o `Function(params, ret)` (`ast.rs:L116-122`). Los nodos AST **no llevan información de tipo** — el mapa `expr_types: HashMap<usize, NormalizedType>` en el `SemanticContext` (`semantic/analyzer.rs:L43`) asocia tipos por `Expr.id`.

**Semántica.** Se implementa como una única pasada dentro de `SemanticAnalyzer::analyze` (`semantic/analyzer.rs:L137-146`). Dentro de `check_declarations` hay múltiples sub-pasadas (`analyzer.rs:L154-...`): (1) registro de tipos y protocolos con detección de ciclos, (2) verificación de firmas de override, (3) registro de funciones globales, (4) análisis de cuerpos de funciones y (5) análisis de cuerpos de métodos. La tabla de símbolos (`semantic/symbol_table.rs`) mantiene una pila de scopes.

**IR — BANNER IR.** Existe una IR propia en `src/ir/` con `IRModule → IRFunction → BasicBlock → IRInstruction → IROperand/IRValueId`. La lowering ocupa 2138 líneas en `ir/lowering.rs`. Los identificadores SSA se generan por `SSAValueGenerator` (`ir/naming.rs`). Existe soporte para `CallIndirect` necesario para dispatch por vtable.

**Backend de generación de código.** Solo hay una implementación real: `LlvmInkwellBackend` en `src/codegen/inkwell.rs` (1484 líneas). Pese a lo que dice el `REPORT.md`, **no existe un `LlvmTextBackend` en el código** — la búsqueda solo la encuentra dentro de `codegen/CODEGEN_ABI.md` como documento, no como implementación. El único backend registrado en `pipeline::codegen` es `LlvmInkwellBackend::new()` (`pipeline/mod.rs:L186`).

**Runtime.** Un runtime en Rust en `runtime-rs/src/lib.rs` (238 líneas) compilado como librería estática `libruntime_rs.a`. Expone funciones con `#[no_mangle] pub extern "C" fn` para: `hulk_concat`, `hulk_num_to_str`, `print_*`, `hulk_alloc`, `hulk_free`, `hulk_strlen`, `range`, `Range_next`, `Range_current`, `hulk_vector_new/push/get/size`, `main` (que llama a `__entry`). La estructura `Range` tiene un `vtable: *mut c_void` en offset 0 para dispatch dinámico uniforme (`runtime-rs/src/lib.rs:L24-30`).

**Flujo nativo.** El módulo `execution.rs` orquesta `scripts/emit_bc_from_ll.sh` (llvm-as → `.bc`) y `scripts/build_from_bc.sh` (opt -O2 → llc `-relocation-model=pic` → clang linkeando con `libruntime_rs.a`).

**Gestión de memoria.** No hay GC. `hulk_alloc` es `libc::malloc`. No hay `hulk_free` invocado automáticamente — leaks intencionales.

**Features en código:**

| Feature | AST | Semántica | Codegen |
|---------|-----|-----------|---------|
| for/range | Sí (`ExprKind::For`) | Sí | Sí (dispatch vtable) |
| is / as | Sí | Sí | **Emite call a `is_T`/`as_T` no implementadas en runtime** |
| protocolos | Sí | Sí | Sí (protocolo methods en vtable) |
| Vectores | Sí | Parcial | **Emite calls a `vector_literal` no existente** |
| Lambdas | Sí | Parcial | Emite función `__lambda_N` pero no captura entorno |
| Macros/define | **No** | **No** | **No** |
| Case | **No** | **No** | **No** |

---

## Bloque 2 — Lexer

El lexer está en `src/lexer/mod.rs` con AFD explícito.

**Operadores.** Todos los operadores importantes están: `+`, `-`, `*`, `/`, `%`, `^` (`mod.rs:L88-102`); `<`, `<=`, `>`, `>=` (`L145-167`); `==`, `!=`, `!` (`L117-143`); `:=`, `:` (`L169-179`); `@`, `@@` (`L181-191`); `->` como `ThinArrow` (`L91-95`); `=>` como `Arrow` (`L123-126`). Los keywords `is`, `as` están registrados en `token.rs:L376-381`.

**Identificadores.** Comienzan con `a-zA-Z`, continúan con `is_alphanumeric() || '_'`. Identificadores con `_` inicial rechazados.

**Números.** Soporta enteros, decimales y notación científica `e`/`E` (`mod.rs:L266-322`). Parsea a `f64`.

**Strings.** Con escapes `\n`, `\t`, `\"`, `\\` explícitos. Escapes inválidos generan error específico. Newline dentro del string rechazado.

**Comentarios.** Soporta `//` de línea y `/* */` de bloque con detección de no cierre. **No soporta `#`**.

**Posición.** Reportada como `Span { file, start_line, start_column, end_line, end_column }`.

---

## Bloque 3 — Parser

**Niveles de precedencia reales en código:**

| Nivel | Función | Operadores | Asoc. |
|-------|---------|------------|-------|
| 0 | `parse_expression` | `let`, `if`, `while`, `for`, `{...}` | control |
| 1 | `parse_assignment_expr` | `:=` | derecha (`mod.rs:L405-428`) |
| 2 | `parse_logical_or` | `\|` | izquierda (`L430-442`) |
| 3 | `parse_logical_and` | `&` | izquierda (`L444-456`) |
| 4 | `parse_equality` | `==`, `!=` | izquierda (`L458-473`) |
| 5 | `parse_comparison` | `<`, `<=`, `>`, `>=` | izquierda (`L475-492`) |
| 6 | `parse_type_operations` | `is`, `as` | izquierda (`L494-512`) |
| 7 | `parse_concatenation` | `@`, `@@` | izquierda (`L514-526`) |
| 8 | `parse_term` | `+`, `-` | izquierda (`L528-540`) |
| 9 | `parse_factor` | `*`, `/`, `%` | izquierda (`L542-557`) |
| 10 | `parse_power` | `^` | derecha (recursión) (`L559-571`) |
| 11 | `parse_unary` | prefijos `-`, `!` | prefijo (`L573-583`) |
| 12 | `parse_call` | `()`, `.`, `[]` | izquierda (`L585-660`) |
| 13 | `parse_primary` | literales, ids, `new`, lambdas, `(...)`, vectores | N/A |

Son **13 niveles reales**.

**Estructuras como expresiones.** `let`, `if`, `while`, `for`, y bloques `{...}` son expresiones que pueden aparecer en cualquier nivel (`mod.rs:L831-842`). **Sí es posible** usar `if` como operando en aritmética. Los bloques devuelven el valor de la última expresión.

**Dangling-else.** Resuelto: `if` requiere `else` obligatorio (`L317-324`) — si no encuentra `else`, sintetiza un literal `0.0`. La gramática también soporta `elif`.

**Recuperación de errores.** Sí, mediante `synchronize()`. Cada regla usa `expect`. En caso de error, se produce un nodo AST placeholder para permitir seguir parseando.

**Lambdas.** El parser tiene `try_parse_lambda` con backtracking sobre el `(` (`mod.rs:L739-811`), y también reconoce `function (...)  =>  expr` (`L920-937`). Soporta anotaciones y tipo de retorno opcional.

**Vectores y comprehensions.** `parse_vector` (`mod.rs:L662-727`) soporta `[e1, e2, ...]` y `[expr || x in iterable]`.

**Tipos parametrizados.** `parse_type_reference` (`mod.rs:L959-1042`) soporta `T*` (iterable), `T[]` (vector), y `(params) -> T` (función).

---

## Bloque 4 — Análisis Semántico

### 4.1 Tabla de símbolos
`src/semantic/symbol_table.rs`. `SymbolTable { scopes: Vec<HashMap<String, SymbolInfo>> }` mantiene stack de scopes. `SymbolInfo` es enum con `Variable`, `Parameter`, `Function`, `Type`, `Protocol`. Se declaran builtins en `declare_builtins` (`L218-341`): `print`, `sqrt`, `sin`, `cos`, `exp`, `log`, `rand`, `range`, `Iterable`, `Range`, `Object`.

### 4.2 Referencias cruzadas
Primera pasada en `check_declarations` (`analyzer.rs:L154-455`) registra todos los tipos y protocolos antes del análisis de cuerpos. Segunda pasada registra funciones globales. Pre-pasada `check_entry_expression` con truncamiento de errores para recolectar signaturas observadas de llamadas.

### 4.3 Scope y variables
`self` se declara como parámetro dentro de scopes de método (`analyzer.rs:L575-583`) — solo disponible dentro de cuerpos de métodos.

### 4.4 Aridad
Verificada dentro de `analyze_expr` con `SemanticError::WrongArgumentCount`.

### 4.5 Inferencia de tipos
Sistema por observación de llamadas: `observed_call_signatures: HashMap<String, Vec<Vec<NormalizedType>>>` (`analyzer.rs:L96`) mantiene los tipos observados en argumentos. No es un HM completo; es una inferencia por uso pragmática.

**LCA para ramas.** `TypeEnvironment::common_supertype` (`type_system.rs:L239-287`) computa el ancestro común caminando hacia arriba.

### 4.6 Verificación de tipos
`expression_checker.rs` verifica operadores binarios: aritmética requiere `Number`/`Unknown`, concatenación acepta cualquier pareja, comparación produce Boolean, lógicos exigen Boolean.

### 4.7 OOP semántico
**Padre existe.** `register_type` en `type_system.rs:L324-390` verifica que el padre esté en `user_types`. Impide heredar de builtins.

**Ciclos.** Detectados por `reaches_target` (`type_system.rs:L357-378`) — DFS con set de visitados. También aplica para protocolos con `extends`.

**Firma de override.** Verificada en `analyzer.rs:L236-311`. Reporta `WrongArgumentCount`, `ArgumentTypeMismatch`, `ReturnTypeMismatch`.

### 4.8 Múltiples errores semánticos
Sí. `SemanticContext::push_error` acumula. Las pasadas continúan aún con errores.

### 4.9 Detección estructural de protocolos
En `check_declarations` (`analyzer.rs:L362-380`), tras registrar métodos de un tipo, se recorren todos los protocolos y se verifica que todos los métodos del protocolo estén presentes en el tipo.

---

## Bloque 5 — Generación de Código

### 5.1 Tipos primitivos en LLVM
`map_type` en `codegen/inkwell.rs:L117-143`:
- Number → `f64` (double)
- Boolean → `i1`
- String, ptr → `ptr` (puntero opaco)
- Objetos → `ptr`

### 5.2 Aritmética
Usa instrucciones float `build_float_add`, `build_float_sub`, `build_float_mul`, `build_float_div` (`inkwell.rs:L681-723`).

### 5.3 Comparaciones
**Manejo dual pointer/float bien resuelto.** El código en `inkwell.rs:L741-1020` verifica primero `both_bool` (usa `build_int_compare`), luego `both_ptr` (usa `strcmp` runtime), y solo si ninguno de esos casos aplica hace `build_float_compare`. Este es el bug crítico que hundió al compilador de Michell Viu; aquí **está resuelto correctamente**. `strcmp` se declara on-the-fly (`L758-770`).

### 5.4 Operadores lógicos
`build_and` / `build_or` directos sobre valores `i1` (`inkwell.rs:L726-738`). **No hay short-circuit**.

### 5.5 Control de flujo
`if`, `while`, `for` en `ir/lowering.rs` producen bloques básicos separados. `lower_for` en `L1665-1736` crea `for_cond`, `for_body`, `for_exit` y emite dispatch vtable para `next()` / `current()`.

### 5.6 OOP / VTable
- **Layout del objeto.** slot 0 = puntero a vtable; slot 1+ = atributos (`lowering.rs:L862-953`). Los heredados primero, luego los propios. **No hay slot dedicado a `type_id`**.
- **VTable.** Construida por `build_vtable_list` (`lowering.rs:L151-190`): primero métodos de protocolos, luego propios, luego heredados no presentes.
- **Emisión.** `emit_vtable_globals` (`L199-225`) emite `__vtable_TypeName` como `IRGlobal`.
- **Dispatch dinámico.** `emit_method_call` (`L227-358`) carga vtable desde offset 0, hace GEP al slot, carga el puntero a función y emite `CallIndirect`.
- **`is`/`as`.** `lower_type_check` y `lower_type_cast` (`L1875-1893`) emiten llamadas a `is_T` y `as_T`. **Estas funciones NO existen en el runtime.**

### 5.7 Linking
`execution.rs:L43-76` invoca scripts que corren llvm-as → opt -O2 → llc → clang con `libruntime_rs.a`.

### 5.8 Backend claim discrepancia
El REPORT afirma dos backends. Grep en `src/` muestra que `LlvmTextBackend` solo aparece como texto en `codegen/CODEGEN_ABI.md`; no existe como implementación de código.

---

## Bloque 6 — Features Opcionales

### [x] Type system
- AST, semántica y codegen completos.
- Tests: `ok/types` 10/10.

### [x] OOP + is/as
- Herencia con override funcional, dispatch dinámico correcto.
- `is`/`as` emiten llamadas a funciones runtime no implementadas.
- Tests: `ok/oop` 10/10 (probablemente no ejercen is/as).

### [x] Iterables / for loops
- Uniforme: dispatch dinámico via vtable a `next()`/`current()`.
- Range builtin y usuario-definidos unificados.

### [x] Protocols
- Conformidad estructural (duck typing estático).
- Detección de ciclos en `extends`.

### [ ] Vectors / arrays
- AST y semántica parcial.
- Codegen emite call a `vector_literal` que no existe en runtime.
- Tests `ok/arrays/*` fallan como se esperaba.

### [ ] Functors
- AST OK, codegen genera función top-level `__lambda_N` sin captura.
- Tests `ok/lambdas/*` fallan.

### [ ] Macros
- Sin soporte en ninguna capa.
- Tests `ok/macros/*` fallan.

---

## Bloque 7 — Precisión del Informe

### 7.1 Afirmaciones verificadas
- Lexer manual como AFD explícito (§3) ✓
- Parser recursive-descent con lookahead (§4) ✓
- AST orientado a expresiones (§4) ✓
- `TypeReference` con Named/Iterable/Vector/Function (§4) ✓
- Tabla de símbolos jerárquica con acumulación de errores (§5) ✓
- Verificación estructural de protocolos (§5) ✓
- BANNER IR con SSA, CFG explícito, `CallIndirect` (§6) ✓
- Runtime en Rust con ABI C, `libruntime_rs.a` (§8) ✓
- Pipeline con paradas intermedias (§9) ✓
- Detección de ciclos de herencia (§5) ✓

### 7.2 Afirmaciones no sustentadas o inexactas

1. **"Dos implementaciones: `LlvmTextBackend` y `LlvmInkwellBackend`"** (§7):
   - Código: solo `LlvmInkwellBackend` existe. `LlvmTextBackend` solo en documento.
   - Clasificación: **descripción incorrecta**.

2. **"`Vectores` tienen soporte parcial [...] integración completa pendiente"** (§12): admisión correcta.

3. **"Cierres con captura de entorno pendientes"** (§12): correcto.

4. **`is`/`as` listado como implementado** (§3): AST/semántica OK, pero codegen emite calls a funciones inexistentes.

### 7.3 Omisiones del REPORT
- Codegen de `is`/`as` es stub.
- El layout de objetos NO tiene slot de `type_id`.
- Detección de comentarios `/* */` de bloque.

### 7.4 Inconsistencias issue vs. código
- **No hay inconsistencias entre lo marcado [x] y lo que efectivamente pasa los tests.**

---

## Bloque 8 — Diagnóstico de Fallas

Todos los tests obligatorios pasan al 100%. Fallos en categorías NO marcadas [x]:

| Categoría | Fallos | Causa |
|-----------|--------|-------|
| `ok/macros/*` | 8 | Sin soporte AST, semántico, ni codegen para `define`/macros. |
| `ok/arrays/*` | 8 | `lower_vector_literal` emite call a `vector_literal` no implementada en runtime. |
| `ok/lambdas/*` | 6 | `lower_lambda` genera función top-level sin captura de entorno. |

**Categorías con éxito 100%:**
- `ok/minimal` 20/20
- `ok/types` 10/10
- `ok/oop` 10/10
- `errors/lexical` 6/6
- `errors/syntactic` 10/10
- `errors/semantic` 15/15
