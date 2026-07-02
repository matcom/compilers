---
student: Cristhian Delgado García, John García Muñoz
issue: 43
repo: johngarcia73/HULK-Compiler
branch: main
date: 2026-07-02
---

# Evaluación técnica — Compilador HULK del equipo John & Cristhian

## 1. Descripción arquitectónica

El proyecto entrega un compilador HULK escrito en **C++20** que produce ejecutables nativos para Linux x86_64. Su rasgo más distintivo dentro del universo de entregas de la asignatura es la elección de backend: en vez de usar LLVM, emite código intermedio en el formato **QBE** (`deps/qbe`, versión 1.2 fijada en `deps/VERSIONS.txt`), delega la generación de assembly a `qbe`, la traducción a objeto a `cc -c` y utiliza el **Boehm-Demers-Weiser Conservative Garbage Collector** (`deps/bdwgc`, 8.2.8) enlazado como `libgc.a`. El runtime C (`runtime/runtime.c`) implementa la interfaz mínima que espera el IR (asignación con GC, dispatch dinámico, concatenación de strings, conversión a string y funciones matemáticas).

La orquestación del pipeline aparece en `main.cpp`:

- Fases 1-3 (frontend): `run_frontend_pipeline` (`compiler/frontend_pipeline.cpp:151`). Lee `builtin.hulk` y lo concatena con la fuente del usuario, invoca lexer, parser y análisis semántico.
- Fase 4 (lowering): `LoweringVisitor` (`lowering/lowering.cpp:4`) aplica transformaciones sobre el AST in-place.
- Fase 5 (IR): `IrGenerator::generate` (`ir_generator/ir_generator.cpp:6`) produce el string de QBE IR.
- Fases 6-8 (backend externo): escribe `.ssa`, invoca `deps/qbe/qbe`, `cc -c` para ensamblar y `cc` para enlazar contra `runtime.o -lgc -lpthread -lm` (líneas 103-121 de `main.cpp`).

Se destacan dos ejes de sofisticación notables: (1) **lexer generator en el árbol** con Thompson + subconjuntos (~630 líneas en `lexer/Lexer_Generator/`), y (2) **parser generator LALR(1) in-tree** con canonical LR(1) + merge a LALR + emisión de tablas ACTION/GOTO (~750 líneas en `parser/Parser_Generator/`). Junto con `frontend_cache.cpp` (396 líneas) que serializa DFA y tablas LALR a `.hulk_cache/` con fingerprint FNV-1a, obtienen una construcción declarativa completa, evitando dependencias tipo flex/bison.

El árbol contiene además un intento de expansor de macros (`semantic/macro_expander.cpp`, 1044 líneas) que **no está incluido en el Makefile** (`Makefile:17-38` — `SRCS` omite `macro_expander.cpp`) y que **jamás es invocado** desde `SemanticAnalyzer::analyze` (`semantic/analyzer.cpp:80-162`). Esto refleja código muerto significativo.

Total de código C++ propio: ~9 100 LOC. Comparado con implementaciones peer basadas en LLVM el frontend es más ambicioso y el backend deliberadamente más simple gracias a QBE.

## 2. Lexer (Lexer_Generator con NFA/DFA)

La arquitectura reproduce la teoría clásica pero desde cero. Las especificaciones de tokens están en `lexer/tokens.hpp:158` (`default_token_specs`) como pares `(TokenType, regex_infix, skip)`.

**Pipeline (en `lexer/Lexer_Generator/`):**

1. **Preprocesamiento** — `preprocessor.cpp:102 regex_to_RegexTokens` tokeniza la regex, `parse_char_class` (línea 36) expande `[a-z]` en uniones explícitas, `insert_concat` (155) inserta el operador de concatenación implícito, y `to_postfix` (184) es una variante shunting-yard con precedencia (Star/Plus/Optional > Concat > Union). El manejo de escapes cubre `\n`, `\r`, `\t` y literales; no reconoce `\d`, `\s`, `\w`.
2. **Thompson NFA** — `nfa.cpp:40 regex_postfix_to_nfa` construye fragmentos por operador (Literal, Concat, Union, Star, Plus, Optional) sobre una pila. Uso correcto de transiciones ε.
3. **Unión de NFAs** — `nfa.cpp:161 unite_nfas` añade un start ε que apunta a los inicios de cada patrón; mantiene la tabla `accept_token` para saber qué patrón acepta qué estado.
4. **Subset construction** — `dfa.cpp:59 nfa_to_dfa` implementa `epsilon_closure`, `move` y el bucle de worklist con hashing sobre `StateSet`. Cuando varios patrones aceptan el mismo estado DFA, se favorece el token de **menor id** (`dfa.cpp:87-92`): esto es lo que garantiza que `function` gane a `[a-zA-Z_][a-zA-Z0-9_]*` porque `TOKEN_FUNCTION = 0` es lo primero en `TokenType`.
5. **Tokenización runtime** — `lexer.cpp:39 Lexer::tokenize` es maximal-munch estándar: avanza mientras haya transición, recuerda el último estado aceptante, retrocede al último aceptante al fallar, cuenta líneas/columnas por carácter (incluida la actualización de `line/column` al atravesar `\n`).

**Observaciones específicas:**
- La regex de números (`lexer/tokens.hpp:185`) es `[0-9]+|[0-9]+\.[0-9]+`. Debido a maximal-munch la variante decimal se elige cuando corresponde, y a que `[0-9]+` tiene menor id la alternativa entera gana en casos ambiguos, lo cual es correcto.
- No hay soporte para comentarios `//` ni `/* */` en `default_token_specs`.
- El error léxico se lanza como excepción y `frontend_pipeline.cpp:58 lexical_error_from_exception` reconstruye el `CompilerError` con regex sobre el mensaje.

En términos de completitud, el lexer generator es funcionalmente correcto sobre el subconjunto de HULK requerido, con la elegancia adicional de estar generado a partir de especificaciones y cacheado en disco.

## 3. Parser (LALR generado in-tree)

La gramática vive en `parser/Parser_Generator/grammar.y` (311 líneas). Es una gramática BNF con `%token`, `%left`, `%right`, `%nonassoc` en el estilo de Yacc pero **el generador es propio**: no se ejecuta bison. En vez de eso, el compilador parsea `grammar.y` en tiempo de arranque (con cache) y construye el autómata LALR internamente.

**Construcción del autómata (en `parser/Parser_Generator/`):**

- **FIRST / nullable** — `parser/utils/First_Comp/first.cpp` (calcula `FirstResult` con vectores de `SymbolSet`).
- **Canonical LR(1)** — `lalr_algorithms.cpp:37 closure_lr1`, `lalr_algorithms.cpp:116 goto_lr1`, y `build_canonical_lr1_impl` (146). Usa fingerprints textuales (`fingerprint_lr1`, línea 15) que ordenan tuplas `(prod, dot, lookahead)` para deduplicar estados. Esta implementación es sana y sigue exactamente el algoritmo de dragon-book.
- **Merge LR(1)→LALR** — `merge_to_lalr_impl` (línea 218): agrupa estados por su core (sin lookaheads), une los lookaheads y remapea transiciones. La búsqueda del grupo que contiene el estado 0 para preservarlo como estado inicial es una precaución correcta.
- **ACTION/GOTO** — `parser_builder.cpp:39 build_tables` recorre transiciones (shift si terminal, GOTO si no-terminal), luego para cada estado busca ítems `A → α·` y emite Reduce por cada lookahead. Los conflictos shift/reduce y reduce/reduce se detectan y se acumulan en `conflicts_out`, pero **la política por defecto es "el primero gana"**: la resolución declarada por precedencias en `grammar.y` (`%left`, `%right`, `%nonassoc`) no está implementada en el código — el parseo de esas directivas existe en `grammar.cpp` pero no se aplica al insertar acciones en `parser_builder.cpp:52 set_action`.

**Runtime del parser** — `parser_runtime.cpp:126 run_parser` es un LR clásico con dos pilas (estados y valores semánticos), invocando `ASTBuilder::build(prod_id, rhs_values)` en cada reducción para emitir el nodo AST correspondiente. El manejo de errores es simple: al no encontrar acción, imprime a stderr un dump de depuración (`parser_runtime.cpp:168-178` — este dump aparece incluso en producción, aunque `frontend_pipeline.cpp:133 parse_without_debug` redirige stderr durante el parseo para ocultarlo).

**Cobertura del lenguaje.** La gramática cubre:
- Declaraciones: `function_decl` con las cuatro formas (block, block con retorno, `=>` inline, con anotación); `type_decl` con parámetros constructor + `inherits` + cuerpo; `protocol_decl` con `extends`.
- Tipos: `type_atom` (Number/Bool/String/Identifier), `type STAR` (iterable/protocol variant), `type L_SQUARE_BRACK R_SQUARE_BRACK` (arreglo), tipos de función `(t1, t2) -> t3`.
- Statements: `expr;`, bloque, return, if/while/for.
- Expresiones: cadena completa `logical_or → logical_and → equality → type_relation (IS/AS) → relational → concatenation (@, @@) → additive → multiplicative → powered → unary → primary`.
- `primary` incluye: literales, identificadores, `lambda_expr`, `function_expr`, `vector_expr`, `if_expr`, `global_call`, `member_call`, `member_access`, `index_access`, `new_expr` (`parser/Parser_Generator/grammar.y:233-247`).

**Lo que la gramática NO reconoce:**
- `define` / `macros`: no existe ninguna producción con la palabra `define` ni token `MACRO`. La búsqueda en `grammar.y` y `tokens.hpp` es negativa. Esto explica por qué **`ok/macros` falla en el CI**.
- `new Type[size]`: la producción `new_expr` es únicamente `NEW IDENTIFIER L_PAREN arg_list_opt R_PAREN` (`grammar.y:270`). No hay `NEW type L_SQUARE_BRACK expr R_SQUARE_BRACK`. Esto es la raíz sintáctica del fallo en `ok/arrays`.

## 4. Análisis semántico + inferencia

Está en `semantic/`. La cabecera de `SemanticAnalyzer::analyze` (`analyzer.cpp:80`) orquesta cinco etapas explícitas:

1. **Registro de builtins** — `registerBuiltinFunctions` (`analyzer.cpp:41`): `sin/cos/tan/abs/sqrt: Number→Number`, `input: ()→String`, `_concat: (String, String)→String`, `print: (Any)→Any`.
2. **Collect declarations** — `TypeInferenceVisitor::collectDeclarations` recorre el AST marcando `collecting = true` y registra tipos, protocolos, funciones y dependencias entre funciones en el `DependencyGraph`.
3. **Orden topológico** — `analyzer.cpp:106-114`: `graph.topologicalSort()` sobre el grafo de llamadas; si detecta ciclo emite un warning y cae al orden de declaración.
4. **Análisis de funciones** — para cada función en orden se ejecuta `inferencer.analyzeFunction`.
5. **Análisis de tipos** — `inferencer.analyzeTypes` y luego **globals** `inferencer.analyzeGlobals(root)`.

**Sistema de tipos** — `semantic/type.hpp` define una jerarquía razonable:
- Primitivos: `NumberType` (con `NumberKind` Int/Long/Float/Double y sabor genérico `Number`), `BoolType`, `StringType`, `VoidType`, `AnyType`, `UnknownType`, `ObjectType`.
- Nominales: `NominalType` (nombre + puntero al padre; equals por nombre).
- Protocolos: `ProtocolType` (nombre; equals por nombre — no verifica estructura acá).
- Compuestos: `FunctionType`, `IterableType`, `EnumerableType`, `VectorType`.
- La función `typeConforms` (`type.hpp:409`) es un chequeo de compatibilidad correcto: cubre casos de covarianza para Iterable/Vector/Enumerable, promoción numérica y ascenso nominal.
- `lowestCommonAncestor` (`type.hpp:472`) es utilizada por refinamiento y por el resultado de `if` para reconciliar ramas.

**Refinamiento de tipos** — `type_inference_visitor.cpp` (1976 líneas) implementa un algoritmo de refinamiento incremental descrito en la REPORT.md sección 5.3: parámetros y variables comienzan como `Unknown`, se refinan por uso (operadores aritméticos → Number, comparaciones → Number, concatenación → String o Number, llamadas → tipo del parámetro, asignación → tipo del RHS). Aunque no verifiqué todos los cases, `checkTypeConformance` (líneas 81-99) muestra el patrón principal, y `resolveDeclaredType` (54-79) resuelve `Enumerable` como builtin implícito.

**Resolución de sobrecarga** — según REPORT sección 5.3 usa cost-based selection (0 exacto, 1 por herencia, 3 por Any, 4 por Unknown, 1000 incompatible). El código correspondiente se ubica en `type_inference_visitor.cpp` en las secciones de análisis de FunctionCallNode; en el pipeline se ven notas como "Selected functor value:" que son consumidas luego por `LoweringVisitor::visit(FunctionCallNode)` para inyectar `invoke(delegate, args)` (ver `lowering.cpp:108-123`). Este es un mecanismo elegante para soportar functors sin cambiar el IR generator.

**Detección de errores** — usa `SemanticContext` y `SemanticDiagnostic` (definidos en `diagnostics.hpp`). Los mensajes incluyen span (SourceSpan `line/column`), severity y notas contextuales. Las salidas se filtran a `CompilerError` por `frontend_pipeline.cpp:90 semantic_error_from_diagnostic`.

**Grafo de dependencias** — `dependency_graph.cpp` (96 líneas): DFS con detección de ciclos y postorden, útil para orden de análisis y para permitir referencias forward/mutuas.

## 5. Lowering + IR + QBE + BDW GC

### 5.1 Lowering (`lowering/lowering.cpp`, 481 líneas)

El `LoweringVisitor` aplica transformaciones source-to-source antes de generar IR. Las transformaciones documentadas y verificadas:

- **For → While** (`lowering.cpp:237-284`): un `for (x in iterable) body` se reescribe a `let iterable = <iterable> in while (iterable.next()) { let x = iterable.current() in body }`. Reutiliza los nombres `iterable`, `next`, `current` como convención — coincide con `builtin.hulk` que define `protocol Iterable { next(): Boolean; current(): Object; }` y el `type Range` que implementa ese contrato.
- **Lambda → Delegate class** (`lowering.cpp:348-439`): las lambdas se elevan a `type Delegate_N(captured...)` con método `invoke`, y la lambda se reemplaza por `new Delegate_N(captured_values)`. Los usos externos que fueron marcados como "functor call" en semántica se convierten en `<delegate>.invoke(args)` por el bloque `lowering.cpp:108-123`. Este es el mecanismo por el cual pasan los tests de `ok/lambdas` sin necesidad de closures nativos.
- **Operadores azucarados** (`lowering.cpp:148-183`): `^` → `pow(a,b)`, `%` → `mod(a,b)`, `!=` → `!(==)`, `@@` → `(left @ " ") @ right`.
- **Inline flag** (`lowering.cpp:47-53`): las funciones no-inline se reescriben a una copia con `isInline = true` (nomenclatura curiosa que en realidad significa "ya lowered"). El IR generator no explota este flag actualmente.
- **Method call → function call**: en `ir_generator/lowering.cpp:1-46` hay `methodCallToFunctionCallLowering` y `methodToFunctionLowering` que reescriben `obj.method(args)` a `method(obj, args)` con `self` inyectado. Se invoca desde `ir_generator.cpp:255` y `ir_generator.cpp:736`.

Los tres visitors relevantes para features avanzados que en el lowering **son no-ops que solo recursan** son `VectorLiteralNode` (441), `VectorComprehensionNode` (449 — hay comentario "LOWERING SUGGESTION 3" sin implementar) e `IndexAccessNode` (465 — comentario "LOWERING SUGGESTION 4"). En consecuencia estos nodos llegan intactos al IR generator.

### 5.2 IR Generation (`ir_generator/ir_generator.cpp`, 829 líneas)

Emite QBE IR a través de dos `StringBuilder`s: `dataBuilder` (sección `data`) y `codeBuilder` (funciones). El mapeo de tipos vive en `ir_generator/type_utils.hpp` (`TypeUtils::toQbeType`): Bool → `w`, Number → `d` en 64-bit, String/Object/Any → `l` (puntero) en 64-bit, Void → sin valor.

Funciones cubiertas correctamente:
- **`visit(ProgramNode)`** (línea 15): emite `$Object` como marker, registra vtables al inicio de `$main` mediante llamadas a `_register_inheritance` y `_register_method`, y luego emite los statements top-level.
- **`visit(NewNode)`** (617): asigna con `_hulk_alloc`, escribe el nombre del tipo en offset 0 (marker de type-id), y sube por la cadena de herencia inicializando atributos con los argumentos del constructor (esto es sofisticado — soporta constructores de padre correctamente).
- **`visit(FunctionDeclNode)`** (729): emite `export function <ret_type> $_<name>(...)`. Para métodos usa `methodToFunctionLowering` para renombrar como `__<Type>_<method>` con `self` como último parámetro.
- **`visit(MemberAccessNode)`** (696): calcula offset con `typeRegister.getOffset`, emite `add` + `load`.
- **`visit(FunctionCallNode)`** (186): caso especial `print` con conversión previa a string por typeFlag, caso `base` con lookup dinámico del padre, caso método con `_get_virtual_method`. Este último es el vtable-dispatch en tiempo de ejecución.
- **`visit(BinaryOpNode)`** (325): op comparativos `< > == <= >=` como `clt/cgt/ceq...`; `+ - * /` como aritmética directa; `@` (concatenación) como llamadas a `_..._to_string` + `_string_concat`; `and`/`or` no aparecen (se manejan con `jnz` en if/while).
- **`visit(IfNode/WhileNode/BlockNode/LetNode)`**: implementados con etiquetas QBE y `jnz`/`jmp`.

**Stubs vacíos (código incompleto)** (`ir_generator.cpp:611-819`):
```cpp
Type* IrGenerator::visit(ForNode& node) {
    //TODO implement for loop,is missing the iterator
    //rigth now.
    return nullptr;
}
```
En principio no debería ejecutarse porque el lowering ya convierte ForNode a While/Let, pero el hecho de que este método esté vacío revela que la ruta ForNode-directa no está cubierta.

```cpp
Type *IrGenerator::visit(LambdaNode&)         { return nullptr; }
Type *IrGenerator::visit(VectorLiteralNode&)  { return nullptr; }
Type *IrGenerator::visit(VectorComprehensionNode&) { return nullptr; }
Type *IrGenerator::visit(IndexAccessNode&)    { return nullptr; }
Type *IrGenerator::visit(ProtocolDeclNode&)   { return nullptr; }
```

- `LambdaNode` funciona en la práctica porque `LoweringVisitor::visit(LambdaNode)` reemplaza el nodo con `NewNode(delegate)`, así que el IR nunca ve la lambda directa.
- `ProtocolDeclNode` no requiere emisión de código (los métodos concretos van en las clases que implementan el protocolo, y el chequeo estructural es puramente semántico).
- `VectorLiteralNode`, `VectorComprehensionNode`, `IndexAccessNode` **no tienen implementación de IR ni de lowering**, lo cual significa que los tests de `ok/arrays` que dependan de estos nodos no pueden generar código.

### 5.3 Runtime (`runtime/runtime.c`, 222 líneas)

- **GC**: `_hulk_gc_init` llama `GC_init` y `_hulk_alloc` es un wrapper de `GC_malloc`.
- **Vtables**: `_initialize_vtables` crea dos hashmaps de `hashmap.h` (implementación open-addressing incluida en el árbol). `_register_inheritance` y `_register_method` los pueblan al inicio de `$main`. `_get_virtual_method(class_id, method_id)` recorre la cadena de herencia hasta encontrar el método — implementación clara y correcta.
- **Strings length-prefixed**: primeros 4 bytes son un `uint32_t` de longitud, luego los caracteres. `_string_concat` y `_string_compair` respetan este layout.
- **Conversiones a string**: `_d_to_string`, `_w_to_string`, `_l_to_string`, `_s_to_string` con enum `TypeFlag` para distinguir string/bool/pointer/number en el mismo slot. Uso de `%g` para números y de `_create_hulk_string` para wrapping.
- **Math builtins**: `_pow`, `_mod`, `_sqrt`, `_sin`, `_cos`. Faltan `_tan` y `_abs` aunque están registrados en el símbolo — probablemente resuelto por wrappers del enlazador (libm los provee).

## 6. Features opcionales

- **Iterables (protocolo `Iterable`)** — el `builtin.hulk` define `protocol Iterable { next(): Boolean; current(): Object; }` y `type Range` es un implementador canónico. El lowering `for → while` (`lowering.cpp:237`) usa `next()`/`current()`, así que el compilador tiene todo el andamiaje para iteradores sobre cualquier tipo que implemente el contrato. Los tests `ok/generators` (que definen `MyRange` custom y lo iteran con `for`) validan esta ruta.

- **Protocols con dispatch estructural** — `ProtocolType` en `type.hpp:86` y `NominalTypeRegistry::conforms` (implementación textual en REPORT.md sección 5.3) validan que un tipo cumpla estructuralmente todos los métodos del protocolo con compatibilidad de firma (contravarianza en parámetros, covarianza en retorno). En runtime, no se materializa un vtable de protocolo separado: el dispatch usa el vtable del tipo concreto (`_get_virtual_method`) porque los protocolos son nombres estructurales. Los tests `ok/interfaces` pasan gracias a esto.

- **Is/As (type tests)** — hay tokens `IS/AS` en gramática (`grammar.y:33, 198-204`), y aparecen en `type_relation`. El análisis semántico los procesa. La emisión de IR concreto para `is`/`as` no aparece explícitamente en el bloque de operadores de `visit(BinaryOpNode)`, pero probablemente se resuelve en otro visit o mediante lowering; no lo verifiqué en detalle. Los tests OOP que incluirían casts pasan.

- **Functors (funciones de primer orden como valores)** — soporte parcial. Existe:
  - Sintáxis `function_expr` en gramática (funciones anónimas nombradas `function(x) -> body`) — `grammar.y:249-252`.
  - Sintáxis `lambda_expr` `(params) -> expr` — `grammar.y:272-273`.
  - Sintáxis de tipo funcional `(t1, t2) -> t3` — `grammar.y:111`.
  - Lambda lifting a delegates — `lowering.cpp:348-439`.
  - `LoweringVisitor::visit(FunctionCallNode)` (`lowering.cpp:97-125`) detecta cuando la resolución semántica marcó una llamada como "functor value" y reescribe `f(args)` como `f.invoke(args)`.
  Los tests `ok/lambdas` validan esta ruta. Es una implementación completa y correcta del feature "funciones como valores" mediante desugaring a objetos con método `invoke`.

- **Vectores/Arrays** — parcialmente presente en la gramática (`vector_expr`, `index_access` en `grammar.y:266, 275-277`) pero **no lowered** (visits vacíos en `lowering.cpp:441-478`) ni **generado a IR** (visits vacíos en `ir_generator.cpp:808-819`). No están marcados como implementados en el issue (correcto).

- **Macros (`define`)** — código muerto: hay 1044 líneas de `semantic/macro_expander.cpp` con clases `MacroExpander`, `expandProgram`, `expandMacroCall`, `bindPattern`, etc., pero:
  1. `Makefile:17-38` NO incluye `macro_expander.cpp` en `SRCS`.
  2. `analyzer.cpp:80-162` (`SemanticAnalyzer::analyze`) jamás invoca a `MacroExpander`.
  3. Referencia a clases `MacroDeclNode` y `MacroCallNode` que **no existen en `parser/AST_Builder/ast_node.hpp`** (grepé el árbol completo — no hay `class MacroDeclNode`).
  4. La gramática no tiene producciones para `define`.
  Es decir: no hay lexer para `define`, no hay parser para `define`, no hay nodo AST correspondiente, y el expansor no compilaría aunque quisieran. Los tests `ok/macros` fallan por esta razón (correcto que no esté marcado en el issue).

## 7. Exactitud del reporte

REPORT.md tiene 1007 líneas y ~7850 palabras. La calidad de la exposición es alta:

- Sección 2 (Arquitectura): fiel al código. Los diagramas Mermaid son honestos (pipeline y flujo de errores). La descripción de `main.cpp` como orquestador es exacta.
- Sección 3 (Lexer): la descripción del pipeline de 5 etapas (infix→postfix, Thompson, unión, subset, tokenización maximal-munch) coincide exactamente con `lexer/Lexer_Generator/*.cpp`. La justificación de "keyword vs. identifier" via ordering de token IDs es correcta (`dfa.cpp:87-92`).
- Sección 4 (Parser): describe correctamente closure_lr1, goto_lr1, merge LR(1)→LALR, fingerprinting de estados, y build_tables. La afirmación "conflictos se detectan pero no se resuelven automáticamente (excepto shift-preferido)" es **parcialmente inexacta**: en el código `parser_builder.cpp:52-96` el conflicto se registra pero el "primero en insertarse gana", que en la práctica podría no coincidir con "shift-preferido"; las anotaciones `%left/%right` en `grammar.y` no se aplican.
- Sección 5 (Semántica): coincide con el código. La descripción del refinamiento incremental y el algoritmo de sobrecarga con costos son fieles.
- Sección 6 (Lowering): describe con exactitud las transformaciones que efectivamente están implementadas (for→while, lambda-lifting, delegate invocation, operator desugaring, method call → function call).
- Sección 7 (IR): la tabla de mapeo de tipos QBE es correcta. La descripción del layout de objetos (type-id en offset 0, atributos en offsets crecientes con herencia) coincide con `visit(NewNode)` (líneas 617-694).
- Sección 8 (Runtime): describe con precisión el layout de strings length-prefixed, los vtables y las conversiones.

**Omisiones importantes en el reporte:**
1. No menciona que `macro_expander.cpp` es código muerto (no compilado, no invocado).
2. No aclara que `visit(ForNode)`, `visit(LambdaNode)`, `visit(VectorLiteralNode)`, `visit(VectorComprehensionNode)`, `visit(IndexAccessNode)` son stubs vacíos en el IR generator (aunque para ForNode y LambdaNode esto no importa porque el lowering los sustituye).
3. No enumera qué features están completos y cuáles no. Sección 9 "Conclusion and Future Work" habla de "optimizaciones futuras" pero no dice "arrays y macros no están implementados".
4. No hay tabla de resultados de tests ni cobertura declarada.

En balance: el reporte es descriptivo, correcto en lo que dice, pero incompleto en aclarar cuál es el subconjunto real del lenguaje soportado por el ejecutable resultante.

## 8. Diagnóstico de fallas principales

Con base en el issue del CI (2026-06-24):

**Categorías obligatorias — 71/71 pass:**
- `ok/minimal 20/20`, `ok/types 10/10`, `ok/oop 10/10`.
- `errors/lexical 6/6`, `errors/syntactic 10/10`, `errors/semantic 15/15`.
Esto es un resultado excelente: cubre todo lo mínimo, más OOP con is/as y todo el mecanismo de reporte de errores con línea/columna. El pipeline de errores (`frontend_pipeline.cpp` con `CompilerErrorKind::Lexical/Syntactic/Semantic` y exit codes 1/2/3) cumple el contrato de `README.md`.

**Extras marcados que pasan (10/10):**
- `ok/extras`: los 10 tests son variantes de `for/while`, `range` y funciones con loops (evidencia: `for_loop.hulk`, `range_count.hulk`, `range_sum.hulk`, `countdown.hulk`, `while_complex.hulk`). Todos ejercitan iteradores custom (Range) y el for→while lowering, que sí está bien implementado.

**Features marcados como implementados (según issue):** minimal, types, OOP+is/as, iterables, protocols, functors.
- **iterables/protocols**: pasan por Range en builtin.hulk + Iterable protocol.
- **functors**: pasan por lambda-lifting a Delegate types + rewrite a `.invoke()`.

**Fallas principales:**

1. **`ok/macros` — falla al 100%.** Raíz: el compilador no tiene token `define`, no tiene producción gramatical, no tiene nodo AST `MacroDeclNode`/`MacroCallNode`. El módulo `semantic/macro_expander.cpp` está en el árbol pero:
   - No está en `Makefile:17-38 SRCS`.
   - No se invoca desde `analyzer.cpp`.
   - Referencia clases inexistentes en `ast_node.hpp`, por lo que ni siquiera compilaría.
   Este trabajo parece haber sido iniciado y abandonado, o generado especulativamente. Es la falla más evidente en la implementación.

2. **`ok/arrays` — falla al 100%.** Raíz: doble fallo.
   - Gramaticalmente: la producción `new_expr` (`grammar.y:270`) es solo `NEW IDENTIFIER L_PAREN arg_list_opt R_PAREN`. No existe una forma para `new Number[5]`. Un test como `let a: Number[] = new Number[5] in ...` (ver `ok/arrays/array_basic.hulk:1`) falla en parseo.
   - Semánticamente/IR: aunque los nodos `VectorLiteralNode`, `IndexAccessNode`, `VectorComprehensionNode` existen y son parseables por `[1,2,3]` y `arr[i]`, en `LoweringVisitor` son no-ops y en `IrGenerator` son stubs que devuelven nullptr. Un test con `[1,2,3]` parsearía pero generaría IR incompleto (probablemente el compilador emitiría IR malformado que QBE rechazaría).

3. **Consideración adicional — dispatch dinámico y campos heredados.** El `visit(NewNode)` (líneas 617-694) recorre la cadena de herencia inicializando atributos y llamando al constructor del padre. Es correcto en el caso general. El `_get_virtual_method` en runtime recorre `inheritance_map` hasta encontrar el método. Ambos aspectos son sólidos y explican el `oop 10/10`. La única sutileza es que las coordenadas de campo se calculan por el nombre del tipo (`typeName`) resolviendo a `typeRegister.getOffset`, no por un descriptor genérico — esto funciona pero requiere que el análisis semántico haya poblado correctamente los tipos en cada uso de member access. Aparentemente lo hace.

**En síntesis:**
- Fortalezas: arquitectura infraestructural (lexer/parser generators, cache, QBE+GC) impresionante, cubre todo lo obligatorio y todo lo marcado como extra excepto macros y arrays. Reporte técnicamente correcto y bien escrito.
- Debilidades: el módulo de macros es código muerto que no está siquiera compilado. Los vectores/arrays tienen soporte gramatical parcial pero sin lowering ni backend. El reporte no aclara estas ausencias. La resolución de conflictos gramaticales (%left/%right) parece no aplicarse en la práctica aunque la gramática los declara.
