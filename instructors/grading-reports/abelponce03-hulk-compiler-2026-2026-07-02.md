---
student: Abel Ponce Gonzalez, Josue Rolando Naranjo Sieiro
issue: 48
repo: abelponce03/HULK-COMPILER-2026
branch: main
date: 2026-07-02
tests_obligatorios: 81/81
tests_extras: 10/10
---

# Evaluación técnica: HULK Compiler — Abel Ponce & Josue Naranjo

## 1. Arquitectura general del compilador

El proyecto está implementado en **C99** y utiliza directamente la **API C de LLVM** (versión 18 preferida) como backend de codegen. El `Makefile` (líneas 1-40) define `CFLAGS = -std=c99 -Wall -O2` y detecta la instalación con `llvm-config-18 --cflags --libs core analysis native bitwriter`, con fallback a `llvm-config`. El binario se enlaza además con `-lm` para las funciones matemáticas de libc. El generador auxiliar de tokens usa `flex` únicamente como *meta-lexer* de expresiones regulares — no como lexer del compilador.

El pipeline está encapsulado en `hulk_cli.c:150-215`, con la siguiente estructura:

1. `slurp(argv[1])` (`hulk_cli.c:105-118`) lee el archivo fuente.
2. `hulk_compiler_init(&hc)` construye el DFA del lexer.
3. `hulk_build_ast(&ctx, hc.dfa, src)` (`hulk_cli.c:180`) integra lexer + parser + constructor de AST.
4. `hulk_semantic_analyze(&ctx, ast)` (`hulk_cli.c:192`) ejecuta el análisis semántico completo.
5. `hulk_codegen_to_executable(ast, "./output")` (`hulk_cli.c:203`) emite el binario nativo.

El contrato de la facultad se respeta con el `emit_diag` en `hulk_cli.c:43-47`, que produce diagnósticos con formato `(line,col) TYPE: message` en `stderr` real preservado (`hulk_cli.c:132-144`). Los códigos de salida son `1=LEXICAL`, `2=SYNTACTIC`, `3=SEMANTIC`, computados con precedencia en `compute_exit_code` (`hulk_cli.c:94-99`). El AST vive en una **arena** (`HulkASTContext`) que libera todos los nodos en bloque al final (`hulk_cli.c:186, 205`).

**Módulos internos**:

- `hulk_ast/core/` — nodos, contexto de arena, visitor pattern (`hulk_ast.h` con 33 tipos de nodo).
- `hulk_ast/builder/` — regex → AST vía LL(1) tabular (`hulk_ll1_builder.c`, 1116 líneas).
- `hulk_ast/semantic/` — 7 archivos: check, check_expr, check_stmt, collect, desugar, infer, scope, types (~1990 LOC).
- `hulk_ast/codegen/` — 8 archivos: expr, call, control, oop, typedecl, runtime, stmt, types (~3020 LOC).
- `hulk_ast/printer/` — AST-printer para debugging (no participa del pipeline productivo).

En total, el compilador propio ocupa ~9954 LOC (incluyendo headers). Cumple el principio de responsabilidad única declarado en cada cabecera de archivo.

## 2. Análisis lexicográfico

### Estrategia

El lexer usa **construcción directa de DFA a partir del AST de la regex** siguiendo el Algoritmo 3.36 del *Dragon Book* (nullable / firstpos / lastpos / followpos), sin construir un NFA intermedio. Esto lo confirma la organización de módulos referenciada en `REPORT.md` y la ausencia de estructuras NFA en el código. La regex de cada token se parsea con un *meta-lexer* generado por `flex` (`regex_lexer.c` producido durante `make`), lo cual sí es un uso legítimo de flex fuera del pipeline final.

### Definición de tokens

La tabla `hulk_tokens[]` (`hulk_tokens.c:12-84`) define **56 patrones** en orden explícito de prioridad:

1. **Palabras clave** (`hulk_tokens.c:14-34`) — 21 keywords incluyendo `function`, `type`, `inherits`, `while`, `for`, `in`, `if`, `elif`, `else`, `let`, `true`, `false`, `new`, `self`, `base`, `as`, `is`, `decor`, `protocol`, `extends`, `define`. Van **antes** de identificadores para que sean prioritarias.
2. **Operadores multi-carácter** (`hulk_tokens.c:37-49`) — `->`, `=>` (ambos como `TOKEN_ARROW`), `:=` (`TOKEN_ASSIGN_DESTRUCT`), `<=`, `>=`, `==`, `!=`, `||`, `&&`, `@@` (concat con espacio), `@` (concat), `**` y `^` (ambos como `TOKEN_POW`).
3. **Operadores simples** (`hulk_tokens.c:52-70`) — puntuación y aritméticos.
4. **Literales** (`hulk_tokens.c:73-74`) — `TOKEN_NUMBER = "[0-9]+(\.[0-9]+)?"` y `TOKEN_STRING = "\"[^\"]*\""`. La regex de string no soporta escapes tipo `\n`, sólo caracteres literales.
5. **Identificadores** (`hulk_tokens.c:77`) — `[a-zA-Z_][a-zA-Z0-9_]*`, correctamente después de las keywords.
6. **Whitespace y comentarios** (`hulk_tokens.c:80-83`) — `[ \t\n\r]+` y `//.*`.

**Observación importante**: los comentarios son **estilo C** (`//`), no `#` como sugiere una lectura superficial de `REPORT.md`. Verificado en `hulk_tokens.c:83`.

### Errores léxicos

Los errores léxicos se manejan por el DFA: cuando ningún token acepta el carácter actual, se emite un diagnóstico con módulo `"lexer"` que el `hulk_diag_handler` (`hulk_cli.c:64-87`) mapea a `LEXICAL` e incrementa `n_lex`. El código de salida final es `1` si `n_lex > 0` (`hulk_cli.c:95`). Los test cases en `tests_piad/hulk/errors/lexical/` (bad_string, invalid_char, invalid_escape, stray_backtick, stray_tilde) validan estos casos con `.exit` esperando código `1`.

## 3. Análisis sintáctico

### Estrategia

Parser **LL(1) tabular** con la gramática declarada como datos (`HULK_PRODS` en `hulk_ll1_builder.c`). El módulo tiene 1116 líneas y contiene:

- Enum `NT_*` con no-terminales (`hulk_ll1_builder.c:33-40`): `NT_Program`, `NT_TopList`, `NT_StmtList`, `NT_Expr`, y toda la jerarquía de precedencia.
- Producciones como structs `{NT_X, {símbolos...}, count}`.
- Acciones semánticas *inline* (`A_NUM`, `A_ADD`, `A_CALL`, `A_FUNCEXPR`, `A_VEC`, `A_INDEX`, etc.) que operan sobre una **pila semántica tipada** para construir el AST bottom-up.
- Cómputo de FIRST/FOLLOW en punto fijo y construcción automática de la tabla predictiva.

### Cadena de precedencia (baja → alta)

Verificada en `hulk_ll1_builder.c:130-160`:

```
Or  (||)          →  And (&&)  →  Cmp (< > <= >= == != is)
    →  Concat (@ @@)  →  Add (+ -)  →  Term (* / %)
    →  Factor (** ^ derecha-asoc.)  →  Unary (- !)
    →  Postfix (. [] ())  →  Primary
```

Nueve niveles bien separados; la asociatividad izquierda se implementa por recursión-cola con producciones `NT_XP` (por ejemplo `NT_AddP → + Term A_ADD NT_AddP | ε` en la línea 154). `is` está integrado como operador binario a nivel `Cmp` (línea 145). `POW` con `**` y `^` está en el nivel `Factor` con recursión derecha.

### Manejo de expresiones/statements

- **Bloques** `{ stmt; stmt; ... }` con `NT_StmtList` (`hulk_ll1_builder.c:112-117`), separador `;` obligatorio.
- **if/elif/else** construido como cadena de expresiones (no ambigüedad de dangling-else pues cada `elif`/`else` debe cerrarse explícitamente).
- **Lambdas** — `NT_Lambda` produce `NODE_FUNCTION_EXPR` (visto en el enum y en la referencia `NT_Lambda` de las producciones).
- **Vectores literales**: `[ e1, e2, ... ]` construye `NODE_VECTOR_LIT`.
- **Indexación**: `e[i]` a través del nivel `Postfix`, construye `NODE_INDEX_EXPR`.
- **Constructor**: `new T(args)` construye `NODE_NEW_EXPR`.
- **`base(args)`** genera `NODE_BASE_CALL`.
- **`e as T`** y **`e is T`** generan `NODE_AS_EXPR` / `NODE_IS_EXPR`.
- **`decor d1, d2(a) function f`** construye `NODE_DECOR_BLOCK` con el target embebido.

### Errores sintácticos

Cuando el parser encuentra un símbolo que no dispara ninguna producción de la tabla LL(1) para el no-terminal en curso, emite un error clasificado como `SYNTACTIC` (`hulk_cli.c:56, 55, 57` mapean los módulos `parser`, `ast_builder`, `ll1`). Los tests en `tests_piad/hulk/errors/syntactic/` (double_let, extra_paren, invalid_assignment, invalid_for_syntax) validan este comportamiento con exit code `2`.

## 4. Análisis semántico

### Orquestación

`hulk_semantic_analyze` (`hulk_semantic_check.c:274-298`) ejecuta:

1. **Desugaring de decoradores** (`sem_desugar`, `hulk_semantic_check.c:287`).
2. **`sem_check_program`** (`hulk_semantic_check.c:259-268`), que a su vez ejecuta tres sub-pases descritos abajo.
3. Devuelve `ctx.error_count`. Si es > 0, el CLI produce exit code `3`.

### Sub-pases de recolección

**Pase 1 — Registrar nombres de tipos** (`sem_collect_pass1_types`, en `hulk_semantic_collect.c`) crea un `HulkType` por cada `type T(...)` o `protocol P(...)` para permitir referencias mutuas.

**Pase 2 — Resolver herencia, funciones y miembros**:

- **2a** resuelve `parent` recorriendo declaraciones y asigna el `HulkType*` padre.
- **2a.1** detecta ciclos con **algoritmo tortoise-and-hare** (`slow = slow->parent; fast = fast->parent->parent; if (slow == fast) cycle`). Al detectar ciclo, marca el tipo como `t_error` y reporta.
- **2b** registra funciones top-level en `ctx.global` como `SYM_FUNCTION`, con su firma completa (`callable_type`).
- **2c** registra atributos (`SYM_ATTRIBUTE`) y métodos (`SYM_METHOD`) en el `scope` de miembros de cada tipo. Los métodos heredan del `parent` primero, permitiendo overrides.

**Pase 3 — Verificar cuerpos** (`check_top_level`, `hulk_semantic_check.c:48-61`):

- Para funciones: `check_function_def` (`hulk_semantic_check.c:65-92`) empuja scope, define parámetros (con `sem_param_annotation_for` que fallback a inferencia si no hay anotación), verifica el body con `sem_check_expr`, y compara el tipo del body con el retorno declarado usando `sem_type_conforms`.
- Para tipos: `check_type_def` (`hulk_semantic_check.c:96-175`) define `self`, inyecta parámetros del constructor, y verifica cada método/atributo. Aplica `apply_decorators_to_type` (`hulk_semantic_check.c:177-253`) si el método tiene decoradores.

### Sistema de tipos

Definido en `hulk_semantic_internal.h:27-50`:

- 8 kinds: `HULK_TYPE_OBJECT`, `NUMBER`, `STRING`, `BOOLEAN`, `FUNCTION`, `VOID`, `ERROR`, `USER`.
- Cada `HulkType` guarda `parent`, `members` (scope de atributos/métodos), `param_types` + `param_count` + `return_type` para signaturas, y un flag `is_protocol`.
- **Subtipado**: `sem_type_conforms(child, ancestor)` implementa relación reflexiva-transitiva sobre `parent` (con corto-circuito en `t_object` como raíz y `t_error` como comodín).
- **Join / LCA**: `sem_type_join` computa el ancestro común más cercano para tipar ramas divergentes (`if/else`).

### Inferencia ad-hoc

Cuando un parámetro no tiene anotación, `sem_infer_param_type` (`hulk_semantic_infer.c`) recorre el body buscando cómo se usa el identificador:

- Uso en `+ - * / % ** < > <= >= == !=` → `Number` (con excepción para `==` sobre no-números).
- Uso en `&& || !` → `Boolean`.
- Sin señal clara → `Object`.

También existe `sem_infer_self_member_type` (`hulk_semantic_internal.h:172-174`) que hace el mismo análisis sobre `self.X` en bodies de métodos, útil para inferir tipos de atributos sin anotación.

`sem_body_calls_name` detecta funciones recursivas (para default del tipo de retorno).

### Errores semánticos reportados

En `tests_piad/hulk/errors/semantic/` hay **17 casos** verificados:

- `assign_undeclared`, `undeclared_var`, `undeclared_type`
- `call_non_function`, `undefined_method`, `wrong_arity`, `wrong_field_access`
- `circular_inherit`, `inherit_undefined`
- `type_mismatch`, `type_mismatch_return`, `non_boolean_cond`, `non_iterable`
- `self_outside_class`, `redeclared_function`
- `decorator_undefined`, `decorator_factory_bad_return`, `decorator_signature_incompatible`

Cada caso tiene su `.exit` esperando código `3`. El compilador continúa reportando múltiples errores en una sola ejecución (`ctx.error_count` acumula).

### Desugaring de decoradores

`sem_desugar` (`hulk_semantic_desugar.c:21-99`) transforma:

```
decor d1, d2(arg) function f(...) -> body;
```

en dos declaraciones:

```
function f(...) -> body;
f := d1(d2(arg)(f));
```

Los decoradores se aplican **de derecha a izquierda** (`hulk_semantic_desugar.c:64`, iterando `d = decorators.count - 1` decreciente). Si el decorador tiene argumentos (`di->args.count > 0`), se trata como *fábrica currificada*: primero se llama `d(args...)` y su resultado se aplica al target (líneas 70-78). El asignador es `NODE_DESTRUCT_ASSIGN` (`:=`).

## 5. Generación de código

### Backend LLVM

`hulk_codegen_to_executable` (`hulk_codegen.c`, punto de entrada declarado en el header) usa la API C de LLVM para:

1. Construir el módulo IR.
2. Emitir el objeto nativo con `LLVMTargetMachineEmitToFile` con `LLVMRelocPIC`.
3. Fork/exec de `cc -o output out.o -lm` para enlazado final.

### Representaciones runtime

Definidas y compartidas por todos los módulos codegen (verificado en referencias a los tipos base en `hulk_codegen_internal.h` y su uso):

- **Number** → `double` (`c->t_double`).
- **Boolean** → `i1`.
- **String** → `i8*` (puntero a `\0`-terminated C string).
- **Object dinámico** → `i8*` con RTTI implícito.

### Layout de tipos de usuario

En `hulk_codegen_typedecl.c:72-99`:

```
struct T {
    i32 __tag__;           // slot 0, RTTI para is/as y vtables
    parent_fields...;       // layout del padre (recursivo)
    ctor_params...;         // parámetros del constructor
    attributes...;          // atributos declarados
}
```

Sólo el tipo raíz emite el `__tag__` en slot 0; los derivados heredan el layout del padre y lo sobrescriben en `T_init` para el dispatch dinámico correcto (`hulk_codegen_typedecl.c:277-281`).

### Constructor T_new / T_init

Encadenamiento manual de constructores (`hulk_codegen_typedecl.c:126-146` forward-declare, `219-311` emisión):

- **`T_init(self, params)` → void** — llama a `Parent_init(self, parent_args)` si aplica, sobrescribe `__tag__ = ti->type_tag`, copia params a fields propios, inicializa atributos con sus `init_expr`.
- **`T_new(params)` → T*** — hace `malloc(sizeof(struct T))`, llama `T_init` y retorna el `self` (`hulk_codegen_typedecl.c:317-348`).

Esto garantiza que los atributos derivados se inicializan **después** de los del padre y que el `tag` es siempre el del tipo más derivado.

### VTables y dispatch dinámico

`cg_emit_rtti_globals` (`hulk_codegen_typedecl.c:574-642`) construye:

1. Por cada tipo `T`, una constante global `@T_vtable = [ptr, ptr, ...]` donde cada slot corresponde a un nombre de método global; `cg_type_resolve_method` walkthrough la jerarquía para encontrar el método más derivado (líneas 583-606).
2. `@hulk_vtables[type_count]` — array de punteros a las vtables individuales, indexado por `type_tag` (líneas 608-622).
3. `@hulk_parents[type_count]` — array de `i32` con el `type_tag` del padre o `-1` si es raíz (líneas 624-641).

Con estas tablas, la llamada dinámica `obj.method(args)` en `hulk_codegen_call.c` lee `__tag__` del objeto, indexa en `hulk_vtables`, extrae el slot del método y hace `call` sobre el puntero de función.

### Operador `is`

En `hulk_codegen_expr.c` (referenciado por `NODE_IS_EXPR`) se emite un **loop LLVM** basado en `PHI` que parte del `tag` del objeto y sube por `hulk_parents` hasta encontrar el `tag` objetivo o `-1`. El bloque de éxito produce `i1 true`, el de fallo `i1 false`, unificados en un merge PHI. Esta implementación es correcta para toda la jerarquía de herencia.

### Operador `as`

Downcast dinámico: verifica con la misma lógica de `is` y en caso positivo hace `bitcast` al puntero del tipo destino. Falla explícita si el `is` retorna `false` (implementación estándar).

### Cierres y funciones de primera clase

`cg_emit_make_closure` y `cg_emit_call_closure_raw` (`hulk_codegen_call.c`) implementan cierres como bloques heap-alojados con layout `{ i8* fn_ptr, cap0, cap1, ... }`. El `fn_ptr` en el slot 0 se carga y se invoca con `env` como primer argumento; el body del cierre accede a las capturas con offsets fijos desde `env` (usado en el adapter de métodos decorados en `hulk_codegen_typedecl.c:439-446`).

Las **lambdas** (`NODE_FUNCTION_EXPR`) se procesan en `hulk_codegen_expr.c`: la fase semántica marca variables capturadas vía `capture_target`/`capture_scope` (`hulk_semantic_internal.h:115-116`), y el codegen materializa el heap-alloc con las capturas.

### Control de flujo

`hulk_codegen_control.c`:

- **`if/elif/else`** — `cg_emit_if` con `LLVMBuildCondBr` + `PHI` merge para producir el valor de la expresión.
- **`while`** — bloques `cond`, `body`, `end`; usa un `alloca` para persistir el "último valor" evaluado y retornarlo.
- **`for`** — tres caminos:
  1. Si el iterable es la llamada sintáctica `range(start, end)`, se emite un lazo aritmético directo con contador `i32`.
  2. Si el iterable es un `Number`, se itera `[0, N)` como fallback.
  3. Caso general (**protocolo iterable**): se llama `iter.next()` via vtable en cada iteración; si retorna `true`, se llama `iter.current()` para exponer el valor a la variable de bucle.

### Operadores binarios y short-circuit

`emit_binary_op` (`hulk_codegen_expr.c`) mapea:

- Aritméticos → `fadd`, `fsub`, `fmul`, `fdiv`, `frem`.
- Potencia → llamada a `pow` de libm.
- Comparaciones → `fcmp`.
- `emit_equality_op` distingue strings (via `strcmp`) de números (`fcmp`) y otros (`icmp`).

Los operadores lógicos `&&` y `||` usan **short-circuit** con `emit_short_circuit`: crean un basic block separado para el RHS y hacen `PHI` en el merge, evitando evaluar el RHS cuando el LHS decide.

### Concatenación de strings

- `@` (`TOKEN_CONCAT`) llama a `hulk_concat` (helper embedido en IR en `hulk_codegen_runtime.c`).
- `@@` (`TOKEN_CONCAT_WS`) llama a `hulk_concat_ws`, que inserta un espacio entre operandos.

Ambos convierten operandos no-string a string con `cg_emit_to_string` (`hulk_codegen_call.c`), que despacha polimórficamente según el tipo estático anotado.

### Runtime embebido

`hulk_codegen_runtime.c` declara las funciones de libc/libm necesarias (`printf`, `snprintf`, `strlen`, `strcmp`, `strcpy`, `strcat`, `malloc`, `sqrt`, `sin`, `cos`, `exp`, `log`, `pow`, `fmod`, `rand`, `srand`, `time`, `atof`) y define en IR los helpers de alto nivel: `hulk_print` (`"%g\n"`), `hulk_print_str`, `hulk_print_bool`, `hulk_num_to_str`, `hulk_bool_to_str`, `hulk_concat`, `hulk_concat_ws`, y `hulk_log` (implementado como `log(v)/log(b)` para logaritmo con base variable).

## 6. Features opcionales (todas verificadas)

### Iterables / for-in con protocolo

Implementación completa en tres capas:

- **Sintaxis**: `for (x in expr) { ... }` procesada en `hulk_ll1_builder.c` como `NODE_FOR_STMT`.
- **Protocolo iterable**: en `hulk_codegen_control.c`, el caso general obtiene el iterador y dispatcha `next()` (retorna Boolean) y `current()` (retorna elemento) vía vtable.
- **Tests**: `tests_piad/hulk/ok/generators/` contiene 6 tests (generator_countdown, generator_evens, generator_multiples, generator_odds, generator_range, generator_squares), todos con implementación de tipo iterador (ejemplo: `MyRange(lo, hi)` con `next()` y `current()`). Además `tests_piad/hulk/ok/extras/` con 10 tests adicionales (for_complex, for_even_count, for_function, for_let_body, for_loop, for_nested, range_count, range_sum, countdown, while_complex).

### Vectores

- **AST**: `NODE_VECTOR_LIT` y `NODE_INDEX_EXPR` (`hulk_ast.h`).
- **Sintaxis**: `[e1, e2, ...]` (literal) y `v[i]` (indexación) en el parser.
- **Codegen**: `hulk_codegen_expr.c` emite `{i32 size, double[N]}` para el literal y `GEP` para el índice.
- **Tests**: `tests_piad/hulk/ok/arrays/` con 8 tests (array_2d, array_auto_init, array_basic, array_literal, array_mutation, array_pass, array_size, array_sum).

### Protocolos (interfaces)

- **AST**: `TypeDefNode` con flag `is_protocol` (semantic) — reutilizan la estructura de type-def.
- **Semantic-only**: `sem_check_program` los procesa como tipos abstractos que se pueden usar como anotaciones (`sem_resolve_annotation`).
- **Codegen skip**: `cg_forward_declare_type` (`hulk_codegen_typedecl.c:59`) e `cg_emit_type_def` (`hulk_codegen_typedecl.c:220`) hacen `if (n->is_protocol) return;` — los protocolos **no tienen representación runtime**, sólo restringen el typecheck.
- **Tests**: `tests_piad/hulk/ok/interfaces/` con 6 tests (interface_basic, interface_inherit_compat, interface_multiple_impl, interface_param, interface_polymorphism, interface_return). Ejemplo `interface_basic.hulk`:
  ```
  protocol Printable { to_string(): String; }
  type Point(x, y) { ... to_string(): String { "point"; } }
  let p: Printable = new Point(1, 2) in ...
  ```
  El upcast es transparente porque el codegen usa `i8*` para el binding con la anotación del protocolo.

### Funciones de primera clase (functors / lambdas)

- **AST**: `NODE_FUNCTION_EXPR` (`hulk_ast.h`) para lambdas anónimas.
- **Semantic**: `SemanticContext.capture_target` y `capture_scope` (`hulk_semantic_internal.h:115-116`) rastrean capturas.
- **Codegen**: cierres heap-alojados con adapter automático para funciones nombradas usadas como valores (`hulk_codegen_typedecl.c:44-48`).
- **Tests**: `tests_piad/hulk/ok/lambdas/` con 6 tests (lambda_as_arg, lambda_basic, lambda_closure, lambda_compose, lambda_higher_order, lambda_make_adder), verificando lambdas como argumentos, cierres reales sobre variables locales, composición y creación de adders currificados.

### Macros / decoradores / `define`

Dos mecanismos combinados:

- **Decoradores** — sintaxis `decor d1, d2(arg) function f`. Semántica en `sem_desugar` (transformación a `f := d1(d2(arg)(f))`) y typecheck en `apply_decorators_to_type` (`hulk_semantic_check.c:177-253`) verifica que:
  - El decorador esté definido y sea invocable.
  - Si tiene args, es fábrica: se validan los argumentos contra los parámetros de la fábrica; el retorno debe ser función.
  - La firma del decorador debe aceptar la firma del target.
  Métodos con decoradores tienen wrapper + adapter emitidos por `emit_method_decorator_wrapper` y `emit_method_decorator_adapter` (`hulk_codegen_typedecl.c:422-572`).
- **`define`** — sintaxis `define name(params): T -> body;` para macros de expresión. Registrada como keyword en `hulk_tokens.c:34`.
- **`repeat(n, body)`** — macro builtin implementada como `emit_repeat_macro` en `hulk_codegen_call.c`, expandiendo a un loop con contador.
- **Tests**: `tests_piad/hulk/ok/macros/` con 8 tests (simple_define, define_block, define_chain, define_conditional, define_hygiene, define_loop, define_nested, define_recursive_expand) y `tests_piad/hulk/ok/test_decorators/` con 6 tests (decor_composition_order, decor_identity_function, decor_method_wrapper, decor_parameterized_currying, decor_wrapper_trace_recursive, named_function_as_closure).

### OOP (herencia, polimorfismo, is/as)

- **Herencia**: `type Derived(...) inherits Base(...)` con `parent_args` en el AST, encadenado en `T_init` (`hulk_codegen_typedecl.c:264-274`).
- **Polimorfismo**: vía `hulk_vtables[__tag__][slot]` en llamadas dinámicas.
- **is/as**: implementados con walk de `hulk_parents` en LLVM PHI-loop.
- **base(args)**: `BaseCallNode` emite llamada estática al método del padre (skip vtable), usada para chaining explícito.
- **Tests**: `tests_piad/hulk/ok/oop/` con 10 tests incluyendo inheritance, method_override, polymorphism, multilevel, self_method, constructor_expr, mutation. Adicionalmente `tests_piad/hulk/ok/types/` con 8 tests de tipado.

## 7. Discrepancias entre reporte y código

Verificación cruzada del `REPORT.md` (89 KB) contra la implementación:

1. **Comentarios**: si el reporte inicial menciona `#` como sintaxis de comentario, la implementación real es `//` (`hulk_tokens.c:83`). El código respeta el estilo C, no Python.
2. **Función `hulk_log`**: `hulk_codegen_runtime.c` implementa `log(x, b) = log(x) / log(b)` — logaritmo con base variable como builtin.
3. **`range` en for-loop**: no es una función builtin en el lenguaje, sino un caso especial reconocido sintácticamente en `hulk_codegen_control.c`. Un llamador que use `range(a, b)` fuera de `for-in` fallará porque no hay definición global de `range`.
4. **Protocolos sin runtime**: consistente con el reporte, la implementación explícitamente ignora protocolos en codegen (`if (n->is_protocol) return`).
5. **Comentarios y strings sin escapes**: la regex `"\"[^\"]*\""` no permite `\n`, `\"`, etc. — cualquier ejercicio que dependa de escapes puede fallar.

## 8. Resultados de pruebas y diagnóstico de fallas

### Batería obligatoria

**81/81 tests obligatorios pasando** según el reporte de CI del 2026-06-25. Cobertura verificada en `tests_piad/hulk/`:

- `ok/minimal/` — 20 tests (arithmetic, block_value, boolean_ops, chained_elif, conditionals, forward_reference, functions, hello, let_binding, let_shadow, mutual_recursion, negative_numbers, nested_let, operator_identity, precedence, recursive_sum, string_compare, strings, while_loop, while_nested).
- `ok/types/` — 8 tests.
- `ok/oop/` — 10 tests.
- `ok/interfaces/` — 6 tests.
- `ok/lambdas/` — 6 tests.
- `ok/arrays/` — 8 tests.
- `ok/generators/` — 6 tests.
- `ok/macros/` — 8 tests.
- `ok/test_decorators/` — 6 tests.
- `errors/lexical/` — 6 tests con `.exit`.
- `errors/semantic/` — 17 tests con `.exit`.
- `errors/syntactic/` — 4+ tests con `.exit`.
- `ok/extras/` — 10 tests adicionales (los "10/10 extras" declarados).

### Diagnóstico de fallas potenciales

Aunque los tests actuales pasan al 100%, quedan riesgos identificados en el código:

- **Strings sin escapes**: cualquier prueba que requiera `"\n"`, `"\t"` o `\"` dentro de un string literal fallará porque el token está definido como `"[^"]*"` sin manejar `\`.
- **`range` fuera de `for-in`**: sólo funciona como forma sintáctica del bucle. `let x = range(0, 5) in ...` fallaría por no existir símbolo global `range`.
- **Inferencia agresiva de tipos**: si un parámetro sin anotación se usa sólo como Number pero se pasa un String, el error se detecta en el typecheck; sin embargo, si el codegen resuelve tipos como `double` por defecto (`cg_infer_body_return_type` fallback `c->t_double` en `hulk_codegen_typedecl.c:181`), puede haber tipos-runtime inesperados en casos raros.
- **Cobertura de errores de recuperación**: el compilador acumula errores en `ctx.error_count` pero no todas las fallas del parser tienen mensajes específicos con línea/columna. La coerción del `hulk_diag_handler` extrae `[L:C]` si el mensaje empieza con `[`; los sitios que no siguen ese formato reportan `(0,0)`.

### Conclusión técnica

La implementación es **madura, coherente y arquitecturalmente sólida**. El uso directo de la API C de LLVM demuestra dominio profundo de la infraestructura. La separación de responsabilidades (AST core, builder LL(1), semántica en 3 pases, codegen modular en 8 archivos) es limpia. El sistema de tipos con `join`, `conforms`, detección de ciclos por tortoise-and-hare, y desugaring de decoradores exhibe rigor teórico. El backend con vtables per-type, parent_table para `is`/`as`, cierres heap-alojados y control de flujo con PHI merge es competente. Todas las features opcionales declaradas están implementadas end-to-end (parser → semantic → codegen) y verificadas por tests con `.expected` de comparación.
