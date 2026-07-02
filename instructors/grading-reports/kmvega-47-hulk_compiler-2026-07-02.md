---
student: Kevin Márquez Vega
issue: 28
repo: kmvega-47/hulk_compiler
branch: main
date: 2026-07-02
---

# Evaluación técnica — Compilador HULK de Kevin Márquez Vega

## 1. Nota importante sobre la evaluación

Esta entrega presenta dos particularidades que deben nombrarse antes de cualquier discusión técnica:

1. **No existe un `REPORT.md`** en el repositorio. `README.md` está presente pero vacío (0 bytes). Toda la evaluación arquitectónica proviene de la lectura directa del código fuente. La rúbrica del curso pesa el reporte como componente independiente, así que su ausencia tiene implicación de calificación además de bloquear la trazabilidad decisión/implementación.
2. **El CI del repositorio no ha producido un build exitoso** desde el 2026-06-13. Los tres primeros intentos fallan sin log de error visible; los del 2026-06-19 fallan con `fatal error: llvm-c/Core.h: No such file or directory` (falta `llvm-config` en el runner); el del 2026-06-22 falla con `/usr/bin/ld: cannot find -lfl` (falta `libfl-dev`). Ambos son problemas del entorno del runner, no del compilador.

Para poder emitir un juicio técnico fundado, el evaluador reprodujo la compilación **localmente**, con todas las dependencias en su sitio (`bison`, `flex`, `libfl-dev`, `llvm-18-dev`, `llc-18` en `PATH`, `gcc` para el enlazado final). En ese entorno **el compilador construye limpiamente y produce un binario `./hulk` funcional**. Todos los resultados de tests reportados abajo provienen de esa ejecución local; **no** son datos del CI.

## 2. Arquitectura del compilador

El proyecto es un compilador HULK escrito en **C (`gnu11`)** con **Flex** para el lexer, **Bison** para el parser LALR(1) y el **API C de LLVM 18** para la generación de código intermedio. El pipeline completo, orquestado por `src/main.c` (119 LOC), es:

```
lexer (flex)  →  parser (bison, LALR(1))  →  AST
                                              ↓
type_inference_visitor  →  constraint_collector  →  type_check_visitor
                                              ↓
                                       codegen_visitor (LLVM 18 C API)
                                              ↓
                                   LLVMPrintModuleToFile → output.ll
                                              ↓
                        llc → .s  →  gcc -c → .o  →  gcc → ./output
```

El total de código C propio ronda las **~5 300 LOC** distribuidas por módulos:

- `src/main.c` (119): orquestación de fases y códigos de salida.
- `src/lexer/hulk_lexer.l` (157): reglas Flex.
- `src/parser/hulk_parser.y` (676): gramática Bison.
- `src/semantic/` (~2 300): tablas de tipos, scope, AST, visitors.
- `src/codegen/` (~1 200): visitor de generación de IR + utilidades LLVM.
- `src/runtime.c` (92): librería runtime en C.
- `lib/collections/`: vectores y listas propios.

El patrón dominante es el **Visitor**: la fase de inferencia (`TypeInferenceVisitor`, 968 LOC), la de colección de restricciones (`ConstraintCollectorVisitor`, 780 LOC), la de chequeo de tipos (`TypeCheckVisitor`, 615 LOC), el `PrintVisitor`, el `FreeVisitor` y el `CodeGenVisitor` (1037 LOC) comparten una vtable común (`src/semantic/visitor/visitor.c`) que se despacha desde `ast_accept`. Es una implementación limpia del patrón — cada visitor tiene su propia estructura extendiendo `Visitor` como base.

`main.c:56-70` implementa un **gating por errores acumulados** en `diagnostic_manager`: la inferencia corre siempre; el chequeo solo si la inferencia no acumuló errores; el codegen solo si el chequeo tampoco. Al final `dm_get_exit_code(dm_global)` mapea la fase más temprana con error al código correspondiente (1 léxico, 2 sintáctico, 3 semántico), lo cual respeta el contrato esperado por el corredor de tests del curso.

El **backend externo** es la parte más frágil operacionalmente. `code_gen_visitor_compile` (`src/codegen/visitor/codegen_visitor.c:980-1037`) escribe `output.ll` con `LLVMPrintModuleToFile` y luego invoca por `system()` la cadena:

```c
llc <ll> -o /tmp/hulk_output.s          // .ll → .s
gcc -c /tmp/hulk_output.s -o .o         // .s  → .o
gcc -c src/runtime.c -o /tmp/hulk_runtime.o
gcc -no-pie .o hulk_runtime.o -o output -lm
```

Este esquema requiere `llc` en `PATH`. Combinado con la ausencia de `libfl-dev` del CI y con `llvm-config` faltando en imágenes de build anteriores, explica por qué **ninguno de los pipelines de CI ha llegado nunca a ejecutar tests**.

## 3. Análisis léxico

`src/lexer/hulk_lexer.l` es un lexer Flex clásico con seguimiento de línea y columna vía `YY_USER_ACTION`. Reconoce:

- **Palabras clave**: `as`, `base`, `function`, `let`, `in`, `if`, `is`, `elif`, `else`, `while`, `type`, `inherits`, `new`, `true`, `false` (líneas 47-61).
- **Operadores compuestos**: `=>`, `==`, `!=`, `>=`, `<=`, `:=`, `**` (líneas 63-69).
- **Operadores simples**: `= + - * / % ^ @ @@ > < & | !` (líneas 71-84). Nota: `&` y `|` son los operadores lógicos AND/OR de HULK (no bit-a-bit).
- **Puntuación**: `( ) { } ; : . ,` (líneas 86-93).
- **Identificadores**: `[a-zA-Z][a-zA-Z0-9_]*`.
- **Números**: `[0-9]+(\.[0-9]+)?`, convertidos a `double`.
- **Strings**: escapes `\n`, `\t`, `\"`, `\\` procesados por `process_string` (líneas 122-158). Para escapes desconocidos (`\z`, por ejemplo) copia el carácter literal en lugar de emitir error — esto explica el fallo de `errors/lexical/invalid_escape` (esperaba exit 1, obtuvo 0).
- **Comentarios**: `//` de línea y `/* */` con estado `<COMMENT>`.

**Ausencias**: no hay tokens para `[`, `]`, `->`, `for`, `protocol`, `interface`, `define`. El comodín `.` en línea 115 captura cualquier carácter no reconocido y emite `LEXICAL: Unexpected character '…'`. Ese comodín es precisamente el que reporta la falla de `ok/arrays/*` — `[` cae en él antes de que el parser pueda opinar.

## 4. Análisis sintáctico

`src/parser/hulk_parser.y` es una gramática Bison LALR(1) de 676 líneas con `%locations` y `parse.error verbose` habilitados. El axioma es:

```
program: type_def_list func_def_list expression SEMICOLON_opt
```

Es decir, el programa completo consiste en **todos los `type`, luego todas las `function`, luego una única expresión** con `;` opcional al final. Esta secuenciación estricta tiene consecuencias que reaparecen en la sección de fallas (§9).

La precedencia y asociatividad (líneas 51-65) es consistente con la del manual:

```
%right IN
%right IF ELIF ELSE
%right WHILE
%right REASSIGN
%left  CONCAT CONCAT_WS
%nonassoc IS AS
%left  OR
%left  AND
%nonassoc EQUALS NOT_EQUALS GREATER GREATER_EQ LESS LESS_EQ
%left  PLUS MINUS
%left  STAR SLASH PERCENT
%right POWER
%right NOT
%left  DOT
```

Las principales producciones semánticas:

- **`type_def`** (línea 121): `TYPE ID params_list_opt type_inheritance LBRACE type_body_elements RBRACE`. Cuerpo con atributos (`var_binding SEMICOLON`) y métodos (`ID params_list type_annotation_opt method_body`) mezclados; internamente se separan en dos listas al reducir.
- **`method_body`** (línea 328): admite `=> expression;` inline o `expr_block` con llaves.
- **`expression`** (líneas 369-556): var refs, literales, paréntesis, unarios `NOT` y `MINUS`, todos los binarios aritméticos/comparativos/lógicos/concatenación, bloques, `IF (…) … elif … else`, `WHILE (…) …`, `LET bindings IN expression`, `ID args_list` (llamada), `expression DOT ID args_list` (método), `attr_access`, `NEW ID args_list`, `assignable REASSIGN expression`, `expression IS ID`, `expression AS ID` y `BASE args_list`.
- **`elif`** se acumula recursivamente y se enlaza vía `append_else` (líneas 669-677).

**Cobertura verificada**: núcleo A.1-A.7, tipado A.8 con anotaciones opcionales, OOP A.9 con herencia y `inherits Base(args)`, `is` / `as`, `base(…)`.

**No implementado en la gramática**:

- **No hay `for`**. La palabra `for` cae en la regla `{LETTER}[a-zA-Z0-9_]*` y se emite como `ID`; el parser interpreta `for(x, ...)` como una llamada de función, luego se atasca en el `in` que sigue. Esto explica los ocho `SYNTACTIC: unexpected IN, expecting RPAREN` de `ok/extras/for_*` y `ok/generators/generator_*`.
- **No hay `protocol` ni `interface`**. Similar: caen como `ID`, y el parser espera EOF después. `ok/interfaces/*` falla con `unexpected ID, expecting end of file`.
- **No hay `define` / macros**. Igual. `ok/macros/*` falla con el mismo mensaje.
- **No hay sintaxis de lambda** `function (x: T) -> body` como valor de primera clase ni `\x -> …`. Al llegar a `let f = function (…)…`, el parser espera un `ID` después de `LET` y encuentra `LPAREN`. `ok/lambdas/*` reporta `unexpected LPAREN, expecting ID`.
- **No hay `[ ]`** para acceso a arreglos ni sintaxis de vectores. El fallo es léxico, no sintáctico.

## 5. Análisis semántico

La semántica está dividida en tres visitors coordinados desde `main.c:58-69` en orden estricto:

**5.1 `type_inference_visitor` (968 LOC)** — recorre el AST fijando `return_type` en cada nodo. Para binarios (líneas 32-40) usa la clasificación de `enums.c`:

- Aritmético → `HULK_NUMBER`.
- Comparación o lógico → `HULK_BOOL`.
- Concatenación → `HULK_STRING`.

**5.2 `constraint_collector_visitor` (780 LOC)** + `type_constraint.c` (336 LOC) — recolecta restricciones de conformidad `CONSTRAINT_CONFORMS` sobre parámetros no anotados, la variable de bucle en `while`, receptores de método, etc. Es la maquinaria más ambiciosa del análisis semántico: intenta unificar múltiples usos de un mismo identificador y elevar al tipo más específico compatible. Ejemplos de sitios donde se emite restricción: `constraint_collector_visitor.c:31` (var refs), `:94` (parámetros de método), `:250` (bindings de `let`), `:306` (destino de `:=`), `:466` (argumentos de invocación de método), `:556` (constructor de `new`), `:616` (argumento de `base(…)`), `:656` (operando de `as`). El sistema es consistente y sano en su diseño.

**5.3 `type_check_visitor` (615 LOC)** — chequeo formal. Este es el visitor con el bug de mayor impacto en tests: `check_binary_operator` (líneas 53-95) trata **todos** los operadores de comparación con la misma regla:

```c
else if (is_comparison_operator(node->operator))
{
    if (!type_conforms_to(left_type, number_type) ||
        !type_conforms_to(right_type, number_type))
        error_msg = "Comparison operator '%s' expected Number and Number";
}
```

Y `is_comparison_operator` (`src/enums/enums.c:109-113`) devuelve `true` para `>`, `>=`, `<`, `<=`, `==` y `!=` sin distinción. Consecuencia: **`bool == bool`, `string == string` y cualquier `T == T` con `T != Number` son rechazados en tiempo de compilación**. Los tests que fallan por esta razón son `ok/minimal/chained_elif`, `ok/minimal/string_compare`, `ok/types/string_return`, `ok/oop/multilevel` y `ok/oop/polymorphism` (todos con el mismo mensaje). En la práctica cualquier programa realista compara booleanos o strings; este es el fallo más impactante en cuanto a número de tests reprobados.

Otras verificaciones bien hechas: unarios (`OP_NOT` requiere `Bool`, `OP_SUB` requiere `Number`, líneas 10-33); condición de `if` y `while` requiere `Bool` (líneas 147-153 y 167-173); consistencia entre tipo anotado y tipo del inicializador en `let` (líneas 198+).

**5.4 Tabla de tipos** — `src/semantic/type_system/type_table.c:14-43` registra los builtins:

```c
"Object", "Number", "String", "Bool", "Void"
```

Nótese que el nombre es **`Bool`**, no `Boolean`. `type_table_lookup_by_name` (línea 100) hace `strcmp(type_a->name, type_b->name)` sin normalización. Cuando un archivo de test usa anotaciones como `: Boolean` (por ejemplo `ok/minimal/mutual_recursion`, `ok/types/annotated`, `ok/types/boolean_return`), la búsqueda falla y se emite `SEMANTIC: Undefined type 'Boolean'`. Los tests del curso usan uniformemente `Boolean`; el compilador reconoce `Bool`. Es una decisión menor de nomenclatura con impacto grande en tests.

**5.5 Control de acceso a atributos** — `ok/oop/vector_math` falla con `Attribute access is private. (only trough self referring to the …)`. El chequeo actual solo permite acceso a atributos vía `self.x`; cualquier `other.x` desde el cuerpo de un método (donde `other` es parámetro del mismo tipo) se rechaza. Esta política es más estricta que lo que exige el test suite.

## 6. Backend / Codegen

`src/codegen/visitor/codegen_visitor.c` (1037 LOC) construye el módulo LLVM sobre `LLVMContext` + `LLVMBuilder` + `LLVMModule`. Los literales (líneas 3-22) producen `LLVMConstReal` para `double`, `LLVMConstInt i1` para bools y `LLVMBuildGlobalStringPtr` para strings. Los binarios (línea 43-55) delegan en `code_gen_build_binary_op` de `src/codegen/utils/codegen_utils.c`. Los condicionales (líneas 75-119) generan bloques `if.then`, `if.else`, `if.merge` y componen un `phi` en el merge — implementación clásica y correcta.

El **runtime** (`src/runtime.c`, 92 LOC) provee las primitivas mínimas: `_hulk_sqrt`, `_hulk_sin`, `_hulk_cos`, `_hulk_exp`, `_hulk_pow`, `_hulk_log` (log de base variable), `_hulk_rand`, `_hulk_print_number` (`%g\n`), `_hulk_print_string` (`%s\n`), `_hulk_print_bool` (`"true"/"false"\n`), `_hulk_concat` (con o sin espacio según `@` vs `@@`), `_hulk_alloc` y `_hulk_free`. La función `_hulk_number_to_string` con `snprintf("%g", …)` habilita el interop de números en concatenaciones.

**Ausencia de VTables explícitas**: la implementación de OOP funciona en los casos simples (`ok/oop/basic_class`, `ok/oop/class_interaction`, `ok/oop/mutation`, `ok/oop/self_method`) pero el fallo de `ok/oop/inheritance` (`expected [Woof|Meow|Woof|] got [Woof|Meow|...|]`) sugiere que el dispatch dinámico para métodos sobrescritos vía puntero al padre no está totalmente correcto — el tercer `print` en el test invoca un método sobre un `Cat` (o similar) tipado como padre, y la implementación devuelve `...` (posiblemente valor no inicializado o llamada al método base).

## 7. Resultados de tests (local, 2026-07-02)

Ejecución local del test runner del curso con todas las dependencias satisfechas:

| Categoría          | Resultado | Notas                                                     |
|--------------------|:---------:|-----------------------------------------------------------|
| `ok/minimal`       | 16/20 [FAIL] | 4 fallos por `==` hardcodeado a Number y por `Boolean`  |
| `ok/types`         |  7/10 [FAIL] | 3 fallos por `Boolean` y por `==` en string_return       |
| `ok/oop`           |  4/10 [FAIL] | Mezcla de `==`, `base`, herencia, `type` después de fn   |
| `errors/lexical`   |  5/6  [FAIL] | `invalid_escape` copia char literal en vez de emitir err |
| `errors/syntactic` | 10/10 [PASS] | Todos los errores sintácticos se detectan correctamente  |
| `errors/semantic`  | 14/15 [FAIL] | 1 fallo: `non_iterable` esperaba exit 3, obtuvo 2        |
| **Total requerido**| **56/71** | **No alcanza el umbral 71/71**                            |
| `ok/extras`        |  2/10 [bonus] | Solo `countdown` y `while_complex`. Falta `for` completo|
| `ok/macros`        |  0/8  [bonus] | No implementado                                          |
| `ok/arrays`        |  0/8  [bonus] | No implementado (falla léxica en `[`)                    |
| `ok/interfaces`    |  0/6  [bonus] | No implementado                                          |
| `ok/lambdas`       |  0/6  [bonus] | No implementado                                          |
| `ok/generators`    |  0/6  [bonus] | Depende de `for`                                         |

## 8. Fallas principales — análisis de causa raíz

### 8.1 `==` limitado a `Number` (5 tests)

En `src/enums/enums.c:109-113`, `is_comparison_operator` retorna `true` para `OP_EQUAL` y `OP_NOT_EQUAL` en el mismo bucket que `>`, `<`, `>=`, `<=`. El chequeo en `type_check_visitor.c:67-71` exige `Number` en ambos lados. La corrección es directa: separar `==` y `!=` en `is_equality_operator` y permitir cualquier par de tipos con `type_conforms_to` bidireccional o al menos ancestro común. Impacto: `chained_elif`, `string_compare`, `string_return`, `multilevel`, `polymorphism`.

### 8.2 Nombre `Boolean` vs `Bool` (4 tests)

`src/semantic/type_system/type_table.c:37` registra el builtin como `"Bool"`; los tests del curso escriben `Boolean` uniformemente. `type_table_lookup_by_name` no aplica alias. La corrección es agregar `register_builtin(table, HULK_BOOL, "Boolean", obj)` alias-de-Bool o normalizar. Impacto: `mutual_recursion`, `annotated`, `boolean_return`, y contribuye a rebotes en cascada en otros tests.

### 8.3 Orden estricto `type_def_list` → `func_def_list` → `expression`

`hulk_parser.y:96-104` obliga a declarar **todos los `type`** antes de cualquier `function`. `ok/oop/constructor_expr` declara primero `function abs_num(...)` y luego `type Box(...)`, y el parser emite `unexpected TYPE` en la línea del `type`. Corrección: `top_level_decl : type_def | func_def; program : top_level_decl* expression SEMICOLON_opt`. Impacto: `constructor_expr` y probablemente otros programas realistas del usuario.

### 8.4 `base` como palabra reservada colisionando con identificadores válidos

El lexer (`hulk_lexer.l:48`) devuelve `BASE` para el lexema `base`. En `ok/oop/method_override:19`, un test hace `let base: Printer = new FancyPrinter("* ", " *") in ...` — un binding con nombre `base`. Como `LET` requiere `ID` y `BASE` no lo es, se reporta `unexpected BASE, expecting ID`. Discusión: hacer `base` un keyword contextual (solo válido dentro de cuerpos de método de tipos que heredan) exigiría cambios en el lexer o el parser; alternativamente, permitir `BASE` como productor en `params_sequence` y `var_binding` como identificador válido resolvería el conflicto sin sacrificar la funcionalidad de `base(…)`.

### 8.5 `for` no existe

Ocho tests de `ok/extras` (todos los `for_*` y `range_*`) más seis de `ok/generators` fallan por la misma razón: no hay token `FOR`, no hay producción `for LPAREN ID IN expression RPAREN expression`. Añadir soporte para `for` con azúcar sobre `while` (que requiere primero un protocolo iterador, o al menos un builtin `range` que retorne algo iterable) es una intervención mediana pero delimitada.

### 8.6 Sin arreglos, ni interfaces, ni lambdas, ni macros

Estos features no están marcados en la lista del issue #28 y su ausencia es coherente con lo declarado; **no descuenta puntos como funcionalidad prometida**. Sí impacta la línea de bonus pero no la de tests requeridos.

### 8.7 Herencia con dispatch incorrecto (1 test)

`ok/oop/inheritance` esperaba `Woof|Meow|Woof|` y obtuvo `Woof|Meow|...|`. La emisión de `...` en el tercer valor sugiere que la vtable del tipo padre no está siendo actualizada con el método sobrescrito al bajar al hijo, o que el codegen está llamando al método del padre directamente cuando el objeto es un `Dog` accedido como `Animal`. Requeriría inspección con `output.ll` sobre el test específico para diagnóstico completo.

### 8.8 `errors/semantic/non_iterable` — exit code

Este test esperaba exit 3 (semántico) y obtuvo exit 2 (sintáctico). Como no hay `for` ni iterables, el compilador falla antes del análisis semántico. Se resolvería en paralelo con §8.5.

### 8.9 `errors/lexical/invalid_escape`

`process_string` (`hulk_lexer.l:141-148`) tiene un `default` que copia el carácter literal para escapes desconocidos. El test esperaba error. Solución: emitir `LEX_ERROR` en el `default`.

## 9. Ausencia de `REPORT.md` y estado del CI

**REPORT.md**. La rúbrica del curso valora el reporte como componente independiente del código — obliga al estudiante a nombrar decisiones, delimitar lo que promete, admitir lo que no está, y facilitar la evaluación. Su ausencia:

- Impide medir la calibración del estudiante entre lo que planeó y lo que entregó.
- Fuerza a inferir la arquitectura desde el código, con pérdida inevitable de la intención autoral (por ejemplo: la decisión de emitir IR de texto y delegar en `llc + gcc` en vez de usar `LLVMTargetMachineEmitToFile` es defendible, pero no sabemos si es una elección informada o un atajo).
- No hay declaración explícita de features implementados vs. omitidos, lo que dificulta separar bugs (== hardcodeado) de decisiones (sin arreglos).
- El `README.md` presente pero vacío señala que no fue un olvido puntual — la documentación no fue prioridad en la iteración.

**CI**. Cuatro corridas en un mes, todas rojas. Los dos errores documentados son de dependencias del runner (`llvm-config`, `libfl-dev`), no de código. Es probable que el estudiante nunca haya visto los tests corriendo bajo CI y haya iterado exclusivamente en local — pero la reproducibilidad forma parte del entregable. El pipeline de CI existente asume un runner del curso con un conjunto conocido de dependencias; si ese runner cambia (por ejemplo LLVM 14 → 18) sin notificación, la responsabilidad del cambio recae sobre el mantenedor del pipeline, no del estudiante. Sin embargo, un `Dockerfile` o instrucciones `apt install` explícitas en el reporte lo habrían mitigado.

## 10. Features declaradas vs verificadas

El issue #28 marca `minimal`, `types` y `oop`. La verificación local muestra:

| Feature marcado | Tests pass / total | Interpretación                                              |
|-----------------|:------------------:|-------------------------------------------------------------|
| minimal (A.1-A.7) | 16/20             | Núcleo aritmético, `let`, `if`, `while`, funciones, strings OK. Los 4 fallos son por bugs semánticos, no por ausencia de features. |
| types (A.8)     |  7/10              | Inferencia y anotaciones funcionan. Los 3 fallos son por el nombre `Boolean` (2) y `==` (1). |
| oop (A.9)       |  4/10              | Instanciación, métodos y `self` OK. Herencia + `base` + polimorfismo tienen fallos. |

Es decir: **de los tres features declarados, ninguno alcanza el 100% de sus tests**. Esto invalida el marcado optimista del issue. Con las correcciones descritas en §8.1-§8.4, la subida sería sustancial: `minimal` recuperaría los 4 (== + Boolean), `types` los 3 (Boolean + ==), y `oop` recuperaría probablemente 3 de los 6 (base como identificador, orden type/function). El escenario razonable tras esas cinco correcciones puntuales sería **~65-67/71**, aún debajo del umbral pero cualitativamente distinto.

## 11. Conclusión

El compilador de Kevin Márquez Vega es una entrega con **inversión técnica real**: ~5 300 LOC de C bien estructurado con patrón Visitor, integración con LLVM 18 vía su API C (que es notoriamente más incómodo que Inkwell o llvmlite), y una maquinaria de inferencia de tipos con recolección de restricciones que va más allá del mínimo. La organización en `include/`, `lib/collections/` propia, separación limpia entre `lexer/`, `parser/`, `semantic/`, `codegen/` refleja disciplina de ingeniería.

Al mismo tiempo, la entrega **no cumple el umbral requerido de 71/71**: pasa 56 de 71. Los fallos se concentran en cinco causas técnicas bien delimitadas — cuatro de ellas (§8.1, §8.2, §8.3, §8.4) son correcciones de menos de 30 líneas de código cada una que subirían el resultado a cerca de 67/71. La quinta (`ok/oop/inheritance`, §8.7) requiere inspección del IR generado. Los features de bonus (arreglos, interfaces, lambdas, macros, generators, for) no están intentados, lo que es coherente con lo marcado en el issue pero limita el techo de bonificación.

El desafío no técnico es **la documentación**. La ausencia de `REPORT.md` y la falta de reproducibilidad en CI son problemas serios para una entrega final: dificultan la evaluación, opacan las decisiones de diseño y obligan al evaluador a inferir intención desde código en vez de recibirla nombrada.

**Recomendaciones concretas para el estudiante**:

1. **Redactar `REPORT.md`** siguiendo el índice del manual: arquitectura general, cada fase (léxico/sintáctico/semántico/codegen), decisiones no obvias (elección de LLVM C API sobre llvmlite, texto IR en vez de bitcode, `llc + gcc` en vez de `LLVMTargetMachineEmitToFile`), lista honesta de features implementados y no implementados, cómo reproducir tests localmente.
2. **Corregir `is_comparison_operator`**: separar equality de ordering, permitir `Bool == Bool` y `String == String`.
3. **Agregar `Boolean` como alias de `Bool`** en la tabla de tipos, o cambiar el builtin registrado a `"Boolean"`.
4. **Relajar el orden `type` → `function`** en el axioma de la gramática.
5. **Solicitar re-run del CI** una vez el pipeline del curso tenga `libfl-dev` y `llvm-config` en el runner, o proveer un `.github/workflows/ci.yml` que instale las dependencias explícitamente antes del `make`.
6. **Inspeccionar `output.ll`** del test `ok/oop/inheritance` para entender por qué el tercer `print` emite `...` en lugar del método sobrescrito.

Con estos seis pasos la entrega se acercaría a los umbrales requeridos y presentaría un frente evaluable en línea con el estándar del curso.
