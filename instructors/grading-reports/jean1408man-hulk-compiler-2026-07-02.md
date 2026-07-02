---
student: Rachel Mojena González, Melissa Maureen Sales Brito, Jean Manuel Martínez Pardo
issue: 31
repo: Jean1408Man/Hulk-Compiler
branch: main
date: 2026-07-02
---

# Evaluación técnica — Compilador HULK del equipo Rachel, Melissa & Jean

## 1. Descripción arquitectónica

Compilador en **C++20** (`Makefile:L4-5`) organizado como pipeline de ocho fases: `lexer → parser → AST → binding → inferencia → typecheck → HulkIR → BannerIR → BannerVM`. El proyecto produce cinco binarios distintos, uno por punto de inspección del pipeline (`Makefile:L96`, targets `lexer`, `parser-demo`, `eval`, `semantic`, `backend`, `build`):

- `hulk_lexer` — solo tokenización.
- `hulk_parser_demo` — parse + print del AST.
- `hulk_semantic` — frontend + análisis semántico (imprime diagnósticos).
- `hulk_eval` — evaluador de árbol (camino A).
- `hulk_backend` — pipeline completo con `--emit-banner`, `--emit-banner-compiled`, `--run-banner`, `--restricted-inference` (`src/backend/main.cpp:L17-60`).
- `hulk` — el binario final que compila IR embebido y lo ejecuta con VM (`Makefile:L278-284`).

Todas las fases están cubiertas por targets de test explícitos (`lexer-nfa-tests`, `parser-tests`, `semantic-tests`, `eval-tests`, `vm-tests`, `backend-tests`, `end-to-end-tests`, `extension-tests`). El diseño de "un binario por fase" es más que cosmético: cada frontera es a la vez un punto de emisión (`--emit-ir`, `--emit-banner`) y un punto de comparación diferencial entre el evaluador de árbol (camino A) y la BannerVM (camino B).

**Sub-lenguajes y IRs**:

1. **HulkIR** (`src/ir/`, código de tres direcciones con nombres de temporales tipo `mul_1`, `call_7`, todavía consciente de tipos).
2. **BannerIR** (`src/banner/`, bytecode linearizado con secciones `.TYPES`/`.DATA`/`.CODE` y `PARAM` explícito antes de cada `CALL`/`VCALL`).
3. **BannerProgram compilado** (`src/vm/banner_vm.cpp`, la VM asigna slots numéricos, IDs de tipo, y linealiza etiquetas a PCs).

**Extensión propia declarada**: type holes explícitos con `_` y `auto` en cualquier posición de anotación, junto con la bandera `--restricted-inference` que exige anotación (concreta o hueco). Está documentada en `REPORT.md §6` (~1200 palabras) e implementada en `src/semantic/analyzer.cpp` (`SemanticPolicyChecker`, L48-217).

**Tamaños relevantes**:

- `src/binding/symbol_resolver.cpp` — 972 líneas (el archivo de análisis estático más grande).
- `src/backend/ir_gen.cpp` — 1248 líneas (lowering AST → HulkIR).
- `src/vm/banner_vm.cpp` — 44 KB, ~1000 líneas (loop de ejecución de la VM).
- `src/parser/parser_tables.cpp` — 167 KB (tabla LR generada, ~4700 productos-estado).
- `tools/parsergen/parsergen.cpp` — 1607 líneas (generador LR(1)/LALR propio).
- `REPORT.md` — 503 líneas, ~3012 palabras.

## 2. Lexer (Thompson NFA)

**Ubicación**: `src/lexer/regex/{thompson,nfa_simulator,regex_ast,nfa}.hpp/.cpp` + `src/lexer/lexer_rules.cpp`.

**Diseño**: expresiones regulares construidas en C++ con combinadores puros (`lit`, `range`, `seq`, `alt`, `star`, `plus`, `opt`, `str`), luego compiladas por construcción de Thompson a un único AFN combinado. El simulador es de conjunto de estados con cierre-ε (**no se determiniza** a AFD).

**Verificación de la construcción de Thompson** (`src/lexer/regex/thompson.cpp:L37-95`):

- `compile_char`: dos estados y una arista sobre `CharSet` (L37-42) — correcto.
- `compile_concat`: enlaza `out(a) → in(b)` con ε (L45-50).
- `compile_alt`: cinco aristas ε en dos triángulos (L53-63) — canónico.
- `compile_star`: seis aristas ε con bucle `out(a) → in(a)` y salida directa `in → out` (L66-75).
- `compile_plus`: reutiliza el bucle de `star` pero **sin** la arista de salto (`in → out`), forzando ≥1 ocurrencia (L78-84).
- `compile_opt`: agrega solo la arista de salto sin bucle (L87-95).

Todos los fragmentos siguen la construcción textual de Aho, Lam, Sethi, Ullman. `build_nfa` (L100-116) crea un `S0` con transición ε a cada regla, y marca cada `out` como aceptante con `priority = i` (orden de declaración). Esto implementa correctamente **priority tie-break por orden de aparición**.

**Longest match** (`nfa_simulator.cpp:L52-104`): mantiene el conjunto activo, avanza carácter a carácter, y en cada paso actualiza `best` si el conjunto contiene algún estado aceptante. La regla es "sobrescribir cada vez" (L96-100), es decir, **maximal munch estándar**. Los desempates entre reglas se hacen por `priority` mínimo (`best_accept`, L31-48).

**Reglas del lexer** (`src/lexer/lexer_rules.cpp:L18-58`): 34 reglas. Los operadores multi-carácter (`:=`, `==`, `=>`, `!=`, `<=`, `>=`, `@@`) están antes de sus prefijos (`:`, `=`, `!`, `<`, `>`, `@`) para que el desempate por prioridad los prefiera cuando ambos son aceptantes — el reporte llama a esto correctamente "longest match declarativo".

**Keywords**: no aparecen en la NFA. Están en `src/lexer/keywords.hpp` como un mapa `unordered_map<string, TokenKind>` (32 entradas verificadas en `token_kind.hpp:L15-83`) y se resuelven post-lexer sobre cualquier `Identifier` reconocido — patrón habitual y correcto.

**Tokens ausentes**: `token_kind.hpp` no define **ni `LBracket`/`RBracket`** ni ningún equivalente `[`/`]`. Tampoco hay `Define`/`Macro`, ni `Arrow` (`->`) para flechas de lambdas. Esta ausencia se propaga: los tests de la suite CI que usan `[…]` fallan en fase léxica (`ok/arrays` — 8 fallas confirmadas por el issue).

## 3. Parser (generado por parsergen)

**Generador propio** en `tools/parsergen/parsergen.cpp` (1607 líneas). Es un LR(1) canónico con **fusión LALR** posterior:

1. `parse_directives` (L274-349): parsea `%start`, `%token`, `%type<...>`, `%left`, `%right`, `%nonassoc` con niveles de precedencia numerados.
2. `ProductionParser` (L351-544): lee producciones separadas por `|` con acciones semánticas `{ ... }` en llaves balanceadas, ignorando strings y comentarios.
3. `compute_first_sets` (L683-723): punto fijo estándar para FIRST y nullable.
4. `build_lr1_automaton` (L809-869): construye el autómata LR(1) canónico con `closure` y `go_to` (L744-802).
5. `merge_lalr_states` (L879-929): reduce LR(1) a LALR por igualdad de core sets (`core_of`, L871-877) — la construcción canónica de Bison.
6. `build_tables` (L1052-1111): produce tabla `action` (shift/reduce/accept) y `go_to`, con resolución de conflictos por precedencia/asociatividad (`resolve_shift_reduce`, L975-1005).
7. Conflictos remanentes se comparan contra `doc/parser/expected_conflicts.txt` (referenciado en `Makefile:L134`). La regla `parser-sync-check-own` (`Makefile:L161-169`) valida en CI que la tabla generada coincide con la commiteada.

Esto es un generador de parsers **completo y auténtico**. La calidad es equivalente a la de Bison para el fragmento LR(1)+LALR. El proyecto también incluye una gramática Bison paralela como oráculo (`src/parser/grammar.y`, 26 KB) y un target `parser-sync-check-bison` (`Makefile:L183-195`) que la corre con `bison -Wcounterexamples`.

**Gramática HULK** (`src/parser/hulk.grammar`, 22 KB): 13 niveles de precedencia (`hulk.grammar:L23-33` — `OR`, `AND`, `EQ`/`NEQ`, `LT`/`GT`/`LE`/`GE`, `IS`/`AS`, `CONCAT`/`DOUBLECONCAT`, `PLUS`/`MINUS`, `STAR`/`SLASH`/`PERCENT`, `CARET`, `NOT`, `UMINUS`). Las secciones `%type` (L35-52) asignan tipos semánticos a los no-terminales — esto es idéntico al modelo Bison.

**Cubre**: declaraciones `function`, `type`, `protocol` con `extends`; `if/elif/else`, `while (…) …`, `for (x in …) …`, `let … in …`, `:=` destructivo, `is`/`as`, `new T(...)`, `base(...)`, `self`, acceso `.`, llamada `()`, bloques `{ ... }`. Cualquier expresión es primaria; `if`/`let` también admitidas como primary (extensión propia declarada en `REPORT.md §2`, resolviendo el shift/reduce a favor de shift para semántica greedy).

**No cubre**: no hay reglas para `[...]`, ni `define`, ni funciones flecha (`\x -> ...`, `fn (x) -> ...`). El `FATARROW` (`=>`) solo aparece en la sintaxis de `function/method_decl` de una línea (`hulk.grammar:L131`, `L276`) — no como lambda.

**AST**: 50+ tipos de nodo agrupados en `src/ast/{literales,binOps,unaryOps,conditionals,loops,domainFunctions,functions,others,types,protocols,variables,assignments,abs_nodes}/`. Todo hereda de `Expr` (que produce valor) o `Decl` (declaración). El patrón Visitor está implementado con `accept(Visitor&)` — cada nueva fase es un visitante independiente.

## 4. Binding phase

**Ubicación**: `src/binding/{symbol_resolver.h/cpp, static_scope.h}`.

`StaticScope` (`static_scope.h:L31-75`) es una tabla anidada con parent-link. Distingue tres tipos de símbolos:

- `VariableBinding*` — bindings de `let`.
- `const Param*` — parámetros de funciones y métodos.
- `SyntheticSymbol*` — símbolos sintéticos (`ForVariable`, `Self`).

**`SymbolResolver`** (`symbol_resolver.h:L138-247`) recorre el AST en tres pases (`run`, `symbol_resolver.cpp:L74-…`):

1. **Registro de declaraciones**: recorre top-level y las inserta en `SemanticTables` (tipos, funciones, protocolos). Esto permite recursión mutua.
2. **Validación de anotaciones** (pase 1.5): comprueba que cada tipo anotado en firmas/atributos exista (`check_type_annotation`).
3. **Resolución de referencias**: recorre expresiones y llena `resolution_map_ : unordered_map<Expr*, ResolutionResult>`. `ResolutionResult` (`symbol_resolver.h:L71-114`) es una unión discriminada con 10 kinds (`Variable`, `Param`, `Synthetic`, `Function`, `BuiltinFunction`, `BuiltinConstant`, `Type`, `Method`, `Attribute`, `Unresolved`).
4. **Checks globales** (`run_checks`, L191-195): `check_inheritance` (ciclos), `check_methods` (override y firmas), `check_protocols`, `check_arities`.

**Puntos notables**:

- **`Iterable*` — protocolos tipados**: `is_typed_iterable_annotation` (L50-52) reconoce anotaciones del tipo `T*` como sintaxis para "iterable de T"; `ensure_typed_iterable_protocol` (`semantic_tables.cpp:L141-163`) genera el protocolo `T*` bajo demanda con método `current(): T`. Esto es una extensión del lenguaje base — el issue no la lista, pero está implementada y usada en tests.
- **Contexto de resolución** (`ResolverContext`, `symbol_resolver.h:L119-124`): 4 valores `Global | Function | TypeAttributeInit | Method` para validar `self`, `base`, etc.

## 5. Análisis semántico

**Ubicación**: `src/semantic/analyzer.{h,cpp}`, con `src/inference/{hulk_type,type_inferencer}.{h,cpp}` y `src/typecheck/type_checker.{h,cpp}`.

`SemanticAnalyzer::analyze` (`analyzer.cpp:L228-257`) orquesta cuatro sub-fases:

1. **Policy check** (`SemanticPolicyChecker`, `analyzer.cpp:L48-217`): recorre declaraciones + expresión global; en modo `--restricted-inference` exige que cada posición de anotación esté anotada concretamente o marcada con `_`/`auto` (`require_annotation`, L79-83). Implementación fiel al pseudocódigo del reporte.
2. **Binding** (SymbolResolver ya descrito).
3. **Inferencia** (`TypeInferencer::infer`, `type_inferencer.cpp:L45-…`): punto fijo con `max_iterations = 10`. Cada iteración recorre el AST, refina tipos monomórficamente. Si tras 10 iteraciones un tipo permanece `Unknown` o `Error`, emite diagnóstico "no se pudo inferir".
4. **Type check** (`TypeChecker::check`): valida conformancia T₁⪯T₂ sobre el mapa de tipos.

**`HulkType`** (`inference/hulk_type.h:L11-56`): 7 kinds (`Number`, `String`, `Boolean`, `Void`, `Object`, `Unknown`, `Error`). `Error` es absorbente (`conforms_to` la propaga silenciosamente). LCA calculado subiendo la cadena `parent_name` (`SemanticTables::find_lca`).

**Builtins pre-registrados** (`semantic_tables.cpp:L30-95`):

- Tipos: `Object`, `Number`, `String`, `Boolean`, `Range` (con `next(): Boolean` y `current(): Number`, L36-49). Nótese que `Range` es un **tipo real** con vtable — no es azúcar.
- Protocolo `Iterable` con `next(): Boolean` y `current(): Object` (L51-60).
- Funciones: `print`, `sqrt`, `sin`, `cos`, `exp`, `log`, `rand`, `range` (L62-82).
- Constantes: `PI`, `E` (L84-93).

**Mapas laterales**: el AST **nunca** se anota. Todos los resultados de análisis viven en `unordered_map<Expr*, X>` en cada fase (resolution_map, type_map, param_types, binding_types, synthetic_types). Esto separa fielmente la sintaxis del análisis y coincide con la práctica de Roslyn (C#) citada en el reporte.

## 6. BANNER VM (bytecode + heap)

**Ubicación**: `src/vm/banner_vm.{h,cpp}`, `src/vm/vm_value.{h,cpp}`, `src/vm/vm_heap.{h,cpp}`.

**Modelo de valores**: `Word = uint64_t` (`vm_value.h:L12`) con 5 kinds (`Number`, `Nil`, `Bool`, `String`, `Object`) empaquetados en NaN-boxing / tagged pointers implícito por las funciones `make_number/make_bool/make_string_ref/make_object_ref` (`vm_value.h:L22-27`). Los refs de string y objeto llevan `generation` para detección de handles obsoletos.

**Heap** (`vm_heap.h`): dos arenas — `objects_` y `strings_` — cada slot con `occupied`, `marked`, `generation`. Free-lists para reuso. `should_collect()` decide cuándo correr GC.

**GC mark-and-sweep** (`banner_vm.h:L108-110`, `gc_roots`, `collect_if_needed`, `enforce_heap_limit`): raíces = todos los slots de todos los frames vivos. Se dispara periódicamente (contador `allocations_since_gc_` en `vm_heap.h:L56`). El reporte lo llama correctamente "GC síncrono con generaciones" — verificado en `VMHeap`.

**Ops** (`banner/banner_ir.h:L13-59`): 42 opcodes. Aritmética (`Add`/`Sub`/`Mul`/`Div`/`Mod`/`Pow`/`Neg`), lógica (`And`/`Or`/`Not`), comparación (`Equal`/`NotEqual`/`Less`/`Greater`/`LessEqual`/`GreaterEqual`), concatenación (`Concat`/`ConcatSpace`), control (`Jump`/`JumpIfTrue`/`JumpIfFalse`/`Label`/`Return`), llamadas (`Param`, `Call`, `VCall` virtual, `SCall` estático), objetos (`Allocate`, `GetAttr`, `SetAttr`, `IsType`, `AsType`), builtins (`Print`, `Sqrt`, `Sin`, `Cos`, `Exp`, `Log`, `Rand`).

**Loop de ejecución** (`banner_vm.cpp:L85-435`): switch clásico sobre `instr.op`. Cada tick incrementa `steps` y respeta `options.max_steps` (default 10^7, `banner_vm.h:L17-21`). Errores runtime son excepciones envueltas en `format_runtime_error` con stack trace.

**Aciertos técnicos verificados**:

- **Slot consistency** (`consistent_field_slots`, `consistent_method_slots`, `banner_vm.h:L86-89`): asigna a cada campo/método el **mismo slot en toda la jerarquía**. Esto permite `GetAttr`/`SetAttr` con índice constante O(1) independientemente del tipo dinámico. Es la implementación canónica de layout aplanado.
- **VCall vs SCall**: `VCall` despacha vía `vtable` del tipo dinámico del receptor (`banner_vm.cpp:L359-385`); `SCall` fija el tipo de partida (`L386-411`) — este último se usa para llamadas `base(...)`.
- **`IsType` / `AsType`** (`L413-427`): comprueba subtipo por herencia; `AsType` lanza runtime error si falla.

**Objects** (`src/objects/hulk_value.{h,cpp}`): estos son los valores usados por el **evaluador de árbol** (camino A), no por la VM. `HulkValue` es un `variant<Nil, double, string, bool, shared_ptr<HulkObject>>`. Esta duplicación es intencional: dos caminos de ejecución independientes que sirven como oráculos diferenciales mutuos.

## 7. Features opcionales

Los features marcados por el equipo en el issue #31 son: `minimal`, `types`, `OOP + is/as`, `iterables`, `protocols`.

| Feature | Marcado | Implementado | Evidencia |
|---|---|---|---|
| `minimal` | Sí | Sí | Aritmética, `let`, funciones, `while`, condicionales en `tests/hulk/ok/minimal/` (20 casos). |
| `types` | Sí | Sí | `type X inherits Y { attr = expr; f() => e; }`, `self`, `base(...)` — `src/ast/types/`, checks en `symbol_resolver.cpp` (herencia + ciclos + override). |
| `OOP + is/as` | Sí | Sí | `IsExpr` y `AsExpr` (`src/ast/types/isExpr.h`, `asExpr.h`); ops `IsType`/`AsType` (`banner_vm.cpp:L413-427`); dispatch virtual real vía `VCall` (`banner_vm.cpp:L359-385`). |
| `iterables` | Sí | Sí | Protocolo `Iterable` builtin (`semantic_tables.cpp:L51-60`); tipo `Range` builtin con `next()/current()` (L36-49); `for x in iter` desazucarado a `while` sobre `next()/current()` en `ir_gen.cpp` (referenciado L241-309). Sintaxis `T*` para "iterable de T" (`symbol_resolver.cpp:L50-62`; `semantic_tables.cpp:L141-163`). |
| `protocols` | Sí | Sí | AST `ProtocolDecl` (`src/ast/protocols/`), gramática `protocol_decl`/`protocol_member` (`hulk.grammar:L173-213`), conformancia estructural (`SemanticTables::type_conforms_to_protocol`, `method_satisfies_protocol`). |
| `vectors` | No | No | Sin tokens `[`/`]` en `token_kind.hpp` o `lexer_rules.cpp`. Sin sintaxis de arrays en `hulk.grammar`. |
| `functors` | No | No | Sin tipo función en el sistema de tipos (`hulk_type.h` solo tiene los 7 kinds). Sin lambdas. |
| `macros` | No | No | Sin `define`/`macro` en `token_kind.hpp` o `keywords.hpp`. |

**Extensión propia declarada** — type holes `_`/`auto` y bandera `--restricted-inference`:

- Sintaxis: `Underscore` y `Auto` en `token_kind.hpp:L82-83`; producciones que aceptan `type_expr` extendidas para cubrir `_` y `auto`.
- Semántica: `SemanticPolicyChecker` (`analyzer.cpp:L48-217`) implementa el predicado `require_annotation` (L79-83); si `restricted && !concrete && !hole`, reporta error con mensaje explícito (`kRestrictedInferenceMessage`, L44-46).
- Inferencia: el `TypeInferencer` de punto fijo (`type_inferencer.cpp:L45-…`) trata huecos como slots `Unknown` que se refinan al recolectar restricciones. `max_iterations = 10` (L46).
- Tests dedicados en `tests/extension/valid_*.hulk` e `invalid_*.hulk` (`Makefile:L352-364`) y suite `end-to-end/cases/08_inference/` + `09_restricted/`.

Esta extensión está bien pensada: es ortogonal (la bandera no cambia el algoritmo de inferencia, solo la política de aceptación), tiene motivación clara (distinguir "olvidé anotar" de "delegué al compilador") y cuenta con pruebas dedicadas.

## 8. Exactitud del reporte

El `REPORT.md` (503 líneas, ~3012 palabras) es **de alta calidad**. Discrepancias detectadas:

1. **§2 "Lexer"**: describe la NFA como "conjunto de estados con cierre-ε, sin determinizar a un AFD". Verificado en `nfa_simulator.cpp:L52-104` — correcto. La afirmación de maximal-munch y desempate por prioridad también es exacta (`best_accept`, L31-48).

2. **§2 "Parser"**: dice "LALR(1)" y "generador propio `parsergen`". Verificado: `parsergen.cpp` construye LR(1) canónico y **fusiona a LALR** con `merge_lalr_states` (L879-929). Correcto.

3. **§2 "Análisis semántico"**: describe tres sub-fases (binding, inferencia, typecheck). En `analyzer.cpp:L228-257` **hay cuatro**: el `SemanticPolicyChecker` corre **antes** de las tres. El reporte lo trata como parte del binding, pero conceptualmente es su propia pasada. Discrepancia menor.

4. **§3 "A.11 Iterables"**: dice "El protocolo Iterable está integrado como builtin". Verificado en `semantic_tables.cpp:L51-60`. **Nota importante**: el firmado del método `current()` en el builtin es `current(): Object`, no `current(): T` como afirma el reporte. La sintaxis `T*` genera un **sub-protocolo** con `current(): T` (`semantic_tables.cpp:L155-160`). El reporte no menciona esta sintaxis `T*`, que es una **extensión no documentada**.

5. **§4 "BannerIR"**: describe tres secciones `.TYPES`, `.DATA`, `.CODE`. Verificado en `banner_ir.h`. Correcto.

6. **§5 "El sistema de tipos"**: los 7 kinds son exactos (`hulk_type.h:L14-21`). La descripción de LCA y absorción de `Error` es fiel al código de `type_inferencer.cpp`.

7. **§6 "Extensión"**: el pseudocódigo de `require_annotation` (líneas 353-361 del reporte) coincide **exactamente** con `analyzer.cpp:L79-83`. El algoritmo de punto fijo también es fiel.

8. **§10 "Limitaciones"**: menciona "GC síncrono" — verdadero (`vm_heap.h:L56 `). Menciona "inferencia monomórfica" — verdadero. Menciona propagación de errores derivados sin supresión — verdadero.

En resumen, el reporte es **muy fiel al código**, con solo dos discrepancias notables: (a) la extensión no documentada del sub-protocolo `T*` para iterables tipados, y (b) contar tres sub-fases semánticas en lugar de las cuatro reales.

## 9. Diagnóstico de fallas principales

Según el issue #31, la CI del 2026-06-22 registra:

- **71/71 tests obligatorios pasan.**
- **10/10 tests extras pasan.**
- **Fallas en**: `ok/macros` (8 tests), `ok/arrays` (8, léxico `[`), `ok/lambdas`.

Diagnóstico verificado en el código:

- **`ok/macros`** — Ausencia total. No hay token `Define`/`Macro` en `token_kind.hpp` (verificado L4-83); no hay reglas de parser para `define` en `hulk.grammar`; no hay nodo AST. El equipo no marcó macros como feature opcional.

- **`ok/arrays`** — Ausencia léxica confirmada. No existe `LBracket` ni `RBracket` en `token_kind.hpp`; `lexer_rules.cpp:L18-58` no incluye reglas para `[`/`]`. En consecuencia, cualquier archivo de test que contenga `[` o `]` genera un `Error` token en el lexer, deteniendo el parseo. El equipo no marcó vectors/arrays.

- **`ok/lambdas`** — Ausencia total. No hay `LambdaExpr` en el AST; el `FATARROW` (`=>`) solo aparece en la sintaxis de `function/method`-declaración inline (`hulk.grammar:L131`, L276), no como constructor de funciones anónimas. No existe tipo función en `HulkType`. No hay token `->` (Arrow) para funciones flecha alternativas. El equipo no marcó functors ni lambdas.

**Todas las fallas corresponden a features que el equipo explícitamente NO marcó** como opcionales en el issue #31. No hay ninguna funcionalidad prometida que esté rota:

- `minimal` — tests `tests/hulk/ok/minimal/` (20 casos) pasan.
- `types` — `tests/hulk/ok/types/` y `tests/hulk/ok/oop/` (20 casos) pasan.
- `iterables` — `tests/hulk/ok/generators/` (6 casos) y `tests/hulk/ok/extras/for_*` (5 casos) pasan; para-basado en el protocolo `Iterable` real.
- `protocols` — `tests/hulk/ok/interfaces/` (6 casos) pasan; conformancia estructural real.

**Cobertura de la extensión propia**: la carpeta `tests/extension/` (`Makefile:L352-364`) y las suites `08_inference/` + `09_restricted/` en `tests/end-to-end/cases/` cubren tanto huecos `_`/`auto` como la bandera `--restricted-inference`, en ambos modos.

**Costo estimado para llegar a cero fallas** (no requerido por el issue):

- **Arrays** `new T[n]` con `[i]`: ~250-400 LOC (2 tokens en NFA + 2 producciones en gramática + `NewArrayExpr` y `IndexExpr` en AST + builtin `__array_alloc/get/set` en runtime).
- **Macros** `define f(x) { … }`: ~250-400 LOC (token + regla + fase de expansión sintáctica pre-semántica).
- **Lambdas** `\x -> e` o `fn (x) -> e`: ~600-1000 LOC (variante AST, tipo función, closures o desazucarado a clase con `apply`, codegen de captura de variables libres).

**Conclusión técnica**: es un compilador **completo, sólido y bien documentado**. La calidad de la implementación (parser generator propio, NFA de Thompson canónico, VM con GC y layout aplanado, 3 IRs con puntos de emisión, dos caminos de ejecución para pruebas diferenciales) supera lo típico de un proyecto docente. La extensión de type holes está bien motivada, cuidadosamente diseñada y ortogonal a la política de la bandera. Los tests fallidos son 100% atribuibles a features no marcadas.
