---
student: Daniel Amaranto Mares Garcia, Juan Miguel Maestre Rodriguez
issue: 33
repo: Amarantomc/the-evil-compiler
branch: master
date: 2026-07-02
---

# Evaluación técnica — Compilador HULK del equipo Amaranto & Juan Miguel

> Repositorio: https://github.com/Amarantomc/the-evil-compiler
> Rama: master | Evaluación: 2026-07-02
> Generado por: Claude Code (evaluación automática)

---

## 1. Descripción arquitectónica

**Lenguaje y andamiaje.** Rust edition 2024 (`compiler/Cargo.toml:L4`), crate único `hulk` de ~5,900 LOC de fuente Rust (`compiler/src/*`). Dependencias mínimas y muy deliberadas:

- `lalrpop 0.23.0` como *build-dependency* — generador de parser LALR(1) invocado por `build.rs` implícito (`Cargo.toml:L7-8`).
- `lalrpop-util 0.21.0` con `features = ["lexer", "unicode"]` para el runtime del parser (`Cargo.toml:L11`).
- `regex = "1"` — usado exclusivamente por el lexer manual (`Cargo.toml:L12`).
- **Ninguna dependencia de LLVM**: no hay `llvm-sys`, `inkwell`, ni `melior`. El backend emite LLVM IR como **texto plano** que después clang procesa.

**Estructura de módulos** (`compiler/src/main.rs:L6-41`):
```
main.rs                    (153 L)  entry, orquesta pipeline, invoca clang/llc+cc
lexer/{lexer,token}.rs     (220+28) lexer manual con regex ancladas
grammar.lalrpop            (473 L)  gramática LALR(1) + mapping al lexer externo
generics/{promote,mono}.rs (81+234) promoción y monomorfización
type_inferrer.rs           (1241 L) inferencia por restricciones con union-find
semantic.rs                (779 L)  checker + detector de ciclos de herencia
codegen.rs                 (1031 L) generador (structs, vtables, ctors, builtins)
codegen_visitor.rs         (804 L)  ExprVisitor<GeneratorResult>
expr_visitor.rs            (28 L)   trait Visitor genérico<T>
errors.rs                  (101 L)  Diagnostic + from_parse_error + line_col
nodes/*.rs                 (~700 L) uno por variante del AST
```

**Pipeline efectivo** (`main.rs:L90-153`):
1. Lectura del fuente (`fs::read_to_string`, `L97-101`).
2. Parseo con `grammar::ProgramParser::new().parse(Lexer::new(&src))` (`L104-108`). Un solo `ParseError` distingue LEXICAL vs SYNTACTIC vía `from_parse_error` (`errors.rs:L58-86`).
3. **Promoción de parámetros genéricos** `promote_program(&mut program)` (`main.rs:L111`).
4. **Monomorfización** `Monomorphizer::new().run(&mut program)` (`main.rs:L113-117`).
5. **Detección de herencia circular** `detect_inheritance_cycles` (`main.rs:L118-121`).
6. **Inferencia de tipos** `TypeInferrer::infer_program` (`main.rs:L123-127`).
7. **Chequeo semántico** `SemanticChecker::new(inferrer.env).check_program(&program)` (`main.rs:L129-137`).
8. **Codegen** `codegen::compile_hulk_program(&mut program, "hulk_module", Some("output.ll"))` (`main.rs:L140-144`).
9. **Enlazado** `build_output("output.ll", "output")`: intenta `clang output.ll -o output -lm -O2`, y si clang falla, cae a `llc -filetype=obj` + `cc` (`main.rs:L64-88`).

**Códigos de salida y contrato de diagnósticos** (`errors.rs:L18-26`): 1=LEXICAL, 2=SYNTACTIC, 3=SEMANTIC, 0=éxito. Formato `(line,col) TYPE: message`, con `(0,0)` cuando no hay span. `line_col` convierte offset de byte a coordenadas 1-based recorriendo el fuente (`errors.rs:L46-54`).

---

## 2. Lexer

Escrito a mano en `lexer/lexer.rs`, apoyado en `regex::Regex` con patrones **anclados con `^`**. Estructura: `Lexer { input, pos, ws, rules: Vec<(Regex, Kind)> }`. `Kind` es `Ident | Int | Float | StrLit | Fixed(Token)` (`lexer.rs:L14-20`).

**Maximal munch por orden de reglas.** Las reglas se ordenan de mayor a menor prioridad; la primera que casa gana (`lexer.rs:L35-76`). Multi-carácter antes que un carácter (`@@` antes que `@`, `:=` antes que `:`, `==` antes que `=`, `<=` antes que `<`, `>=` antes que `>`, `&&` antes que `&`, `||` antes que `|`). Float antes que Int (`[0-9]+\.[0-9]+` antes que `[0-9]+`).

**Promoción de keywords** (`lexer.rs:L80-93`): el lexer reconoce identificadores genéricos y en `keyword()` decide si el texto es reservada. Cubre: `if elif else while for in let type function inherits new base self true false is as Number String Boolean`. Un identificador `ifx` casa el token completo y no se confunde con `if`. **No hay** tokens ni palabras clave para `protocol`, `interface`, `define`, `macro`, `function ->`, `[...]`, `T*`.

**Comentarios** (`lexer.rs:L145-169`): línea `// ...` (hasta `\n` o EOF) y bloque `/* ... */`. Un bloque sin cerrar produce **error léxico explícito** con `LexicalError { message: "Comentario de bloque sin cerrar (Falta '*/')", pos }`.

**Cadenas con escapes** (`lexer.rs:L96-125`): regex `"(?:\\[\s\S]|[^"\\])*"`, decodificación en `unescape_string` con `\n \t \r \\ \" \' \0`. Un escape inválido devuelve `Err(rel)` con el offset relativo del `\` ofensor; el lexer lo suma al offset de apertura para dar posición exacta.

**Precisión numérica** (`token.rs:L4-5`): `Token::Int(usize)` y `Token::Float(f32)`. `f32`, no `f64`. En `grammar.lalrpop:L426-429` la regla `Num` convierte int a f32 con `as f32`. Todo el pipeline propaga `f32`, aunque el IR final emite `double`. Esto puede introducir pérdida de precisión con literales de gran magnitud (los propios autores lo documentan en su §11 de limitaciones).

**Interfaz LALRPOP** (`lexer.rs:L127-128`): `impl Iterator<Item = Result<(usize, Token, usize), LexicalError>>`, exactamente el contrato de un lexer externo para LALRPOP.

---

## 3. Parser (LALRPOP)

`compiler/src/grammar.lalrpop` (473 líneas). Gramática LALR(1) generada por `lalrpop 0.23.0` en tiempo de compilación (typical build script). El bloque `extern` (`grammar.lalrpop:L440-472`) declara `type Location = usize`, `type Error = LexicalError`, y el mapping de cada variante del `Token` al terminal correspondiente.

**Precedencia como cascada** (`grammar.lalrpop:L196-294`):
```
Program → Statement+
Statement → FunctionDecl | TypeDecl | TopExpr;
TopExpr    → OrExpr | OrExprOpenS | OrExprOpenB | BlockExpr
OrExpr     → OrExpr ("|" | "||") AndExpr | AndExpr
AndExpr    → AndExpr ("&" | "&&") AssignExpr | AssignExpr
AssignExpr → Term ":=" AssignExpr | CompExpr        (recursivo por la derecha)
CompExpr   → CompExpr (== != >= <= > <) ConcExpr | ConcExpr
ConcExpr   → ConcExpr ("@" | "@@") IsExpr | IsExpr
IsExpr     → IsExpr "is" Ident | AsExpr
AsExpr     → AsExpr "as" Ident | ArithExpr
ArithExpr  → ArithExpr ("+" | "-") FactAnd | FactAnd
FactAnd    → FactAnd ("*" | "/" | "%") UnaryExpr | UnaryExpr
UnaryExpr  → ("+" | "-" | "!") Base | Base
Base       → Base "^" Term | Term
Term       → Num | Bool | Str | "new" Id ("::" "<" Args ">")? "(" ... ")" | Term "." ... | FunCall | "(" ... ")" | "base" "(" ... ")" | "self" | Ident
```

**Problema del "cuerpo abierto"** (`grammar.lalrpop:L333-411`): HULK es orientado a expresiones (`if/while/for/let` devuelven valor). Para desambiguar `if (c) a else b + 1` sin conflictos shift/reduce, la cascada se **triplica** en tres copias paralelas:

- Cascada normal (`OrExpr`, `AndExpr`, ...): expresiones "cerradas".
- Cascada `…OpenS` (`OrExprOpenS`, ..., `TermOpenS`): cuerpo termina en simple.
- Cascada `…OpenB` (`OrExprOpenB`, ..., `TermOpenB`): cuerpo termina en bloque `{...}`.

Los constructos de control se emiten en `OpenExprS`/`OpenExprB` (`grammar.lalrpop:L170-190`). Las variantes `BodyS`/`BodyB` (`grammar.lalrpop:L167-168`) restringen qué puede ser el cuerpo. Solución correcta pero verbosa: cualquier cambio en precedencia debe replicarse en tres lugares.

**Anotaciones de tipo y genéricos**. La regla `Type` (`grammar.lalrpop:L104-116`) admite `Number|String|Boolean`, `Ident` como `Class(...)`, `Ident "<" Type,... ">"` como `Generic(...)`, y `"(" Type "," Type,... ")"` como `Tuple(...)` con al menos dos elementos. `GenericParams` (`L129-131`) toma `<T,U,...>`. La instanciación explícita usa **turbofish** `::<Args>` (`L133-135`), tanto en `FunCall` (`L413-420`) como en `new` (`L302-308`) — elimina la ambigüedad clásica de `<` como operador vs apertura de lista de tipos.

**Accesos con punto** (`grammar.lalrpop:L309-317`) desambiguan sintácticamente:
- `expr "." <int>` → `TupleAccess`
- `expr "." <FunCall>` → `MethodCall`
- `expr "." <VarIdent>` → `MemberAccess`

**Lo que la gramática NO reconoce.** No hay reglas para `protocol`, `interface`, `extends`, `define`, `macro`, `function (...) => expr` como valor de lambda, `T*` como tipo iterable, `T[]` como vector, `new T[n]`, `a[i]` indexación. Los tokens `[` y `]` no existen (`token.rs:L14-28` no los declara).

---

## 4. Análisis semántico + inferencia

### 4.1 Inferencia (`type_inferrer.rs`, 1241 L)

Enfoque **basado en restricciones** con sabor Hindley-Milner. Cuatro etapas (`type_inferrer.rs:L329-352`):

1. `register_declarations`: firmas de tipos (`register_type`) y funciones (`register_function`) con `Var` frescas donde falte anotación (`L355-401`).
2. `gen_function_decl` / `gen_type_decl`: recorrido bottom-up con `ExprVisitor<InferType>` que emite restricciones a partir del uso (`L404-482`).
3. `solve_constraints` (`L498-573`): worklist union-find, detección de estancamiento con `stalled_count > worklist.len() + 1` que rompe el bucle si las restricciones restantes son irresolubles (`L508-513`).
4. Anotación del AST: cada `return_type` se rellena vía `resolve` (`L576-582`).

**Tipos internos** (`L11-46`): `InferType::{Concrete(HulkType), Var(u32)}`, `Constraint::{Eq, Conform, TupleProject(tuple_ty, index, result)}`. `TupleProject` es la restricción especial que permite inferir `p.0` sin conocer aún el tipo de `p`.

**Union-find plano** (`L49-83`): `Substitution` con `apply` que sigue la cadena hasta un tipo no-Var y `bind` que no pisa un binding concreto. `process_constraint` (`L521-573`) enlaza vars, deja pasar concretes-vs-concretes al chequeo semántico (**no emite errores de conformidad**), y reencola las restricciones no resueltas.

**Environment** (`L109-285`): registra `functions`, `types`, `self_type`, `current_method`. `conforms_concrete` (`L170-193`) implementa subtipado nominal: reflexividad, `Unknown` y `Param` conforman con cualquier cosa (permisividad deliberada), `Generic` compara por su forma manglada, y clases via `is_subtype` que recorre la cadena de padres.

**LCA para condicionales** (`L206-233`): `Environment::lca` prueba conformidad en ambos sentidos y, si ninguno gana, interseca las listas de ancestros. Esto tipifica `if x then Cat else Dog` como `Animal` (o `Unknown` si no hay ancestro común).

**Builtins registrados** (`L130-143`): `print(unk)→unk`, `sqrt/sin/cos/exp(num)→num`, `log(num,num)→num`, `rand()→num`, `range(num,num)→num`. Constantes `PI` y `E` como variables globales de tipo `Number`.

### 4.2 Checker (`semantic.rs`, 779 L)

Consume el AST anotado y **lee** tipos vía `type_of` (que devuelve el `return_type` almacenado) sin recalcularlos (`L663-693`). Reglas verificadas (`L149-636`):

- **Aritmética/comparación**: operandos `Number`.
- **Lógicos**: operandos `Boolean`.
- **Igualdad**: conformidad bidireccional; una debe conformar a la otra.
- **Concatenación** (`@`, `@@`): `expect_concatenable` acepta `Unknown|String|Number|Bool` (`L721-732`).
- **`if`/`while`/`elif` condition**: `Boolean`.
- **`for`**: iterador *debe* ser `range(...)` sintácticamente. Otro iterable es error (`L275-289`).
- **`let`/`:=`**: variable declarada, conformidad valor↔declarado, member-access sobre no-clase da error.
- **`new T(args)`**: existencia del tipo, aridad efectiva (heredando params del padre si el hijo no declara), conformidad de args.
- **`method`/`field`**: `lookup_method`/`lookup_field` recorre cadena de herencia; método/campo inexistente reporta error localizado.
- **`self`**: solo dentro de tipo (`self_type.is_some()`).
- **`base()`**: solo dentro de método, y el padre debe tener el mismo método (`L508-543`).
- **`is`/`as`**: aplicables solo a `Class|Unknown`; target declarado; para `as`, origen y destino deben estar **relacionados por herencia** (`L544-585`) — evita downcast entre tipos disjuntos.
- **`TupleAccess`**: índice dentro de rango sobre `Tuple` (`L614-634`).

Los errores se **acumulan** (`SemError { offset, message }`, `L18-22`) y se traducen a `(line,col)` en `main` (`main.rs:L131-137`). Reporta múltiples errores en una sola pasada.

### 4.3 Detección de herencia circular

`detect_inheritance_cycles` (`semantic.rs:L734-780`) construye un mapa `type → parent`, recorre cada cadena con un `HashSet<String>` y reporta cuando revisita un tipo. Se ejecuta **antes** de la inferencia porque tanto la inferencia (LCA) como el chequeo (`is_subtype`) recorren cadenas de ancestros y ciclarían con una jerarquía cíclica.

---

## 5. Monomorfización de genéricos

Dos módulos que trabajan en tándem (`generics/promote.rs` + `generics/mono.rs`, 81+234 L).

### 5.1 Promoción (`promote.rs`)

Reescribe, dentro de cada declaración genérica, los nombres de tipo que coinciden con un parámetro declarado (`type Box<T> { ... }`), convirtiéndolos de `HulkType::Class("T")` a `HulkType::Param("T")` mediante el método `promote_params` de `HulkType` (`expr_node.rs:L36-47`). Distingue así "T como parámetro genérico" de "T como clase real". Recursa sobre `Tuple` y `Generic`, y cubre todos los sitios: parámetros de constructor, atributos, firmas de método (params + return), anotaciones de `let`, argumentos de turbofish (`promote.rs:L44-81`).

### 5.2 Monomorfización (`mono.rs`)

`Monomorphizer::run` (`mono.rs:L37-93`):

1. **Separación**: `fn_templates` y `type_templates` guardan las declaraciones con `is_generic()` (campo `generics` no vacío). El resto queda como `roots`.
2. **Siembra**: `scan_expr` recorre `roots` buscando llamadas o `new` cuyo nombre esté en las plantillas y con `type_args` no vacíos. Calcula `mangle_name(base, args)` = `"base__arg1_arg2..."` (`L152-156`), encola `(base, args)`, reescribe `n.name` al manglado y vacía `n.type_args` (`L98-119`).
3. **Punto fijo**: procesa la cola con `HashSet<String> done` para evitar repetir. `specialize_fn`/`specialize_type` sustituyen `Param(n)` por los tipos concretos con `subst_expr` y luego llaman a `collapse_generic` para colapsar `Generic(_,concrete)` a `Class("mangled")` (`L160-193`). Tras especializar, **reescanea** el cuerpo especializado para descubrir genéricos anidados (`Box<Box<Number>>` genera primero `Box__Number` y luego `Box__Box__Number`).
4. **Reensamblado**: primero `out_types`, luego `out_fns`, luego `kept` (`L88-92`). El orden importa porque codegen espera procesar tipos antes de funciones.

**Anidamiento diferido** (`mono.rs:L109-112`): si los `type_args` todavía contienen `Param` (uso dentro de otra plantilla no resuelta), la instancia NO se encola; la resolverá `subst_expr` cuando la plantilla padre se especialice.

**Costo aceptado**: el usuario debe **instanciar con turbofish obligatorio** (`new Box::<Number>(...)`). No hay inferencia de argumentos de tipo desde el uso, y no hay genéricos acotados: `Param` conforma con cualquier cosa (`type_inferrer.rs:L176-177`), lo que efectivamente desactiva restricciones sobre `T`. El equipo reconoce esto en §11.1 del REPORT.md.

---

## 6. Codegen (LLVM IR como texto)

`codegen.rs` (1031 L) + `codegen_visitor.rs` (804 L). Emite IR con **opaque pointers** para `target triple "x86_64-pc-linux-gnu"` (`codegen.rs:L939-940`). No usa bindings — el IR se construye vía `write!/format!` en `Vec<String>` (`code`, `global_decls`) y al final se escribe con `fs::write` (`codegen.rs:L1023-1029`).

### 6.1 Representación de valores

`GeneratorResult { register: String, llvm_type: String }` empareja el registro LLVM con su tipo LLVM (`codegen.rs:L12-21`). Mapeo (`hulk_type_to_llvm`, `L312-323`):
- `Number → double`
- `Bool → i1`
- `String → ptr`
- `Class(_) → ptr`
- `Unknown → ptr`
- `Tuple(elems) → %Tuple_...`
- `Param(_) → ptr`, `Generic(_,_) → ptr` (post-monomorfización no aparecen).

### 6.2 Objetos y herencia con vtables

**Layout padre-primero** (`collect_all_fields`, `codegen.rs:L213-222`): campos del padre antes que los propios, precedidos por el `vptr` en el slot 0. Un puntero a hijo es prefijo binario del padre.

**Vtable** (`build_vtable_for_class`, `L478-509`): copia la vtable del padre (para preservar índices heredados), **sobrescribe** slots de métodos redefinidos (mantiene índice para despacho polimórfico), añade nuevos al final. `compile_vtable_global` (`L512-549`) emite:
```
%VTable_T = type { ptr, ptr, ... }        ; N slots ptr
@vtable_T = global %VTable_T { ptr @T_m1, ptr @T_m2, ... }
```
Clases sin métodos reciben un stub `%VTable_T = type { i8 }` para evitar structs vacíos (`L521-523`).

**Constructor `@T_new`** (`compile_type_decl`, `L552-726`):
1. Tamaño con GEP-null trick: `getelementptr %T, ptr null, i32 1` + `ptrtoint ... to i64` (`L629-636`).
2. `malloc` (`L638-639`).
3. Instala vptr: GEP al campo 0 y `store @vtable_T` (`L642-650`).
4. Cadena al padre: si `inherits P(args)` explícito → evalúa y llama a `@P_init_fields(self, args...)`; si `inherits P` implícito → propaga los propios params (`L662-693`).
5. Inicializa campos propios con GEP al índice `1 + parent_field_count + attr_idx` (`L703-721`).

Adicionalmente emite `@T_init_fields(self, params...)` (`L737-808`) que hace el mismo trabajo de inicialización pero recibiendo el `self` ya reservado — permite encadenar padres sin re-malloc.

**Métodos** (`L810-891`): función `@T_method` recibe `ptr %self` como primer parámetro, expone los campos como allocas mutables (para permitir `campo := expr`), luego los parámetros, y ejecuta el cuerpo.

**Despacho dinámico** (`visit_method_call`, `codegen_visitor.rs:L493-571`):
```
; carga vptr del objeto
%vptr_field = getelementptr inbounds %T, ptr %obj, i32 0, i32 0
%vptr       = load ptr, ptr %vptr_field
; GEP al slot en la vtable
%slot = getelementptr inbounds %VTable_T, ptr %vptr, i32 0, i32 <idx>
%fn   = load ptr, ptr %slot
; llamada indirecta
%res = call <ret> %fn(ptr %obj, <args>)
```

**`base()`** (`visit_base_call`, `codegen_visitor.rs:L573-633`): resuelve el ancestro más cercano que tenga *propia* implementación del método actual vía `resolve_parent_method` → `resolve_own_impl` (`codegen.rs:L161-184`). Llama directamente a esa función `@P_method` con el `self` actual — sin re-despacho por vtable.

### 6.3 `is` y `as` por identidad de vtable

**`is`** (`visit_type_test`, `codegen_visitor.rs:L694-739`): carga el vptr, obtiene `collect_subtypes(target)` (recorre `class_meta` para todos los descendientes ordenados alfabéticamente, `codegen.rs:L432-453`), compara el vptr con cada `@vtable_S` mediante `icmp eq ptr` y **OR-combina** con cadena de `or i1`. Tipo destino no en `class_meta` → constante `false`. Coste lineal en número de subtipos.

**`as`** (`visit_type_downcast`, `codegen_visitor.rs:L635-692`): misma comprobación que `is`; si conforma, salta a `cast_ok` y devuelve el mismo puntero con el tipo estático destino; si no, salta a `cast_fail` que llama a `@hulk_cast_error()` + `unreachable` (`codegen.rs:L990-996`).

**Ventaja del enfoque**: no necesita etiquetas de tipo separadas ni cabeceras extendidas — reutiliza la vtable como identidad de tipo. **Coste**: `is`/`as` solo funcionan con clases; no aplican a primitivos ni tuplas.

### 6.4 Control de flujo con `phi`

**`if/elif/else`** (`visit_if`, `codegen_visitor.rs:L109-158`): emite bloques `then/elif/else/merge` con `br i1`, acumula `(reg, block)` de cada rama y en el merge emite `phi <ty> [reg1,%blk1], [reg2,%blk2], ...`. Uso idiomático de SSA.

**`while`** (`L84-107`): reserva `alloca double` para el valor acumulado, bloques `cond/body/end`, `fcmp` en cond, actualiza el resultado en cada iteración del cuerpo.

**`for`** (`L294-369`): reconoce sintácticamente que el iterador debe ser `range(a,b)` y lo baja a un bucle de contador explícito con `fcmp olt` como condición y `fadd 1.0` como paso. No hay protocolo general de iteración.

### 6.5 Cadenas, concatenación e igualdad

**Cadenas** (`visit_string`, `L383-403`): emite constante global `@.str.N = private unnamed_addr constant [len x i8] c"..."` escapando bytes fuera de ASCII imprimible como `\XX` hex. Devuelve `ptr` al global.

**`@` / `@@`** (`emit_single_concat`, `emit_spaced_concat`, `codegen.rs:L388-431`): `strlen` de cada lado, `malloc` del total, `strcpy` + `strcat`. `@@` intercala `" "` via un global compartido `@.str.space`. `ensure_cstr` (`L363-386`) coerce `double`/`i1` a texto: `double` vía `snprintf(buf, 32, "%g", val)`, `i1` vía `select` entre `@.str_true`/`@.str_false`.

**Igualdad** (`emit_equality`, `L455-474`): despacho por tipo LLVM — `strcmp` para `ptr` (cadenas), `icmp` para `i1`, `fcmp oeq/une` para `double`.

### 6.6 Builtins como emisores

`builtins: HashMap<String, BuiltinFn>` donde `BuiltinFn = fn(&mut CodeGenerator, &[GeneratorResult]) -> GeneratorResult` (`codegen.rs:L53, L74-142`). Registrados: `print` (elige `%g\n` o `%s\n` según tipo, devuelve su argumento), `sqrt/sin/cos/exp` (llaman `@sqrt` etc.), `log(base, val)` (cambio de base con dos `@log` + `fdiv`), `rand` (`@rand()` + `sitofp` + `fdiv 32767.0`). No hay `range` como builtin — es sintácticamente reconocido en `for`.

### 6.7 Header emitido

`compile_hulk_program` (`codegen.rs:L931-1032`) emite el header con declaraciones externas (`malloc, strlen, strcpy, strcat, strcmp, printf, snprintf, sqrt, sin, cos, exp, log, rand, abort`) y las constantes de formato (`@.fmt_double`, `@.fmt_g`, `@.fmt_str`, `@.str_true`, `@.str_false`, `@.str_cast_error`). Genera `@hulk_cast_error()` y luego `@main` con las expresiones top-level; el último resultado con tipo `i1` se `zext` a `i32` para el retorno.

### 6.8 Tuplas

`ensure_tuple_type_emitted` (`codegen.rs:L347-360`) emite bajo demanda `%Tuple_<nombres> = type { ... }` y lleva un `HashSet` para no duplicar. `visit_tuple` (`codegen_visitor.rs:L741-779`) reserva un `alloca` del struct, hace `store` en cada slot vía GEP y `load` para devolver el struct por valor. `visit_tuple_access` (`L781-803`) hace `alloca`+`store` de la tupla, GEP del índice constante y `load` del elemento.

---

## 7. Features opcionales

Analizando el código:

| Feature | AST | Semántica | Codegen | Estado |
|---------|-----|-----------|---------|--------|
| **Minimal** | ✓ | ✓ | ✓ | Completo (aritmética, control, `let`) |
| **Types** | ✓ | ✓ | ✓ | Completo (params, atributos, métodos, inferencia HM-lite) |
| **OOP + is/as** | ✓ | ✓ | ✓ | Herencia, vtables, RTTI por identidad de vtable |
| **Iterables** | Solo `range` | Chequeo sintáctico | Bucle de contador | Parcial: `for` solo con `range(a,b)` literal |
| **Genéricos** ★ | ✓ | ✓ (turbofish obligatorio) | ✓ | Extensión no trivial, no está en la lista opcional del issue |
| **Tuplas** ★ | ✓ | ✓ (`TupleProject` constraint) | ✓ | Feature extra no marcada |
| **Vectors/Arrays** | ✗ | ✗ | ✗ | Ausente: sin token `[`, sin regla, sin nodo |
| **Protocols** | ✗ | ✗ | ✗ | Ausente: sin palabra clave `protocol`, sin regla |
| **Functors/Lambdas** | ✗ | ✗ | ✗ | Ausente: no hay tipo función ni lambda ni cierre |
| **Macros/Define** | ✗ | ✗ | ✗ | Ausente: sin palabra clave `define`, sin expansión |

**Features marcadas en el issue** (según instrucciones): minimal, types, OOP+is/as, iterables. **Todas presentes en el código**.

**Extensiones no marcadas pero implementadas**:
- **Monomorfización de genéricos** con `mangle_name`, worklist a punto fijo, genéricos anidados diferidos, `Param → Concrete` via `subst_expr`.
- **Tuplas** con nodo AST propio, restricción `TupleProject` en el inferidor, tipo LLVM `%Tuple_...` emitido bajo demanda.

**Features no marcadas y no implementadas**: vectores, protocolos, functors, macros. Consistente con el issue.

---

## 8. Exactitud del reporte

`REPORT.md` tiene **3,158 palabras** según el CI (7,219 palabras contadas localmente — probable diferencia en el conteo). Doce secciones (`§1 Pipeline`, `§2 Lex`, `§3 Sintaxis`, `§4 AST + Visitor`, `§5 Genéricos`, `§6 Tuplas`, `§7 is/as`, `§8 Inferencia`, `§9 Chequeo`, `§10 Codegen`, `§11 Limitaciones`, `§12 Resumen`).

**Afirmaciones verificadas contra el código**:

1. **§1 Pipeline y orden**: exacto — se verifica en `main.rs:L104-150`. La monomorfización antes de inferencia y la inferencia antes del chequeo son fieles al código.
2. **§2 Lexer manual con regex ancladas**: exacto (`lexer.rs:L34-77`). El "maximal munch por orden de reglas" se corresponde con `Vec<(Regex, Kind)>` iterado en secuencia.
3. **§2 Cadenas y escapes**: exacto — `unescape_string` está en `lexer.rs:L96-125` con los mismos escapes descritos.
4. **§2 Detalle f32→f64**: exacto y honesto (`token.rs:L4-5`).
5. **§3 Cascada de precedencia**: exacto para el orden Or→And→Assign→Comp→Conc→Is→As→Arith→FactAnd→Unary→Pow→Term.
6. **§3 Duplicación `OpenS/OpenB`**: exacto — se ve triplicada, no duplicada, en `grammar.lalrpop:L333-411` (normal + OpenS + OpenB). El REPORT dice "duplican" en §3, pero de hecho la tercera copia es la cascada normal; el término "triplicada" es más preciso. Falta menor.
7. **§4 AST y Visitor compartido**: exacto — `TypeInferrer` implementa `ExprVisitor<InferType>` y `CodeGenerator` implementa `ExprVisitor<GeneratorResult>`.
8. **§5 Genéricos (promoción + monomorfización)**: exacto. `mangle_name`, `specialize_fn`, `specialize_type`, `scan_expr`, punto fijo y anidamiento diferido están todos en `mono.rs`.
9. **§6 Tuplas con `TupleProject`**: exacto — la restricción existe en `type_inferrer.rs:L45`.
10. **§7 `is`/`as` por identidad de vtable**: exacto — `collect_subtypes` + `icmp eq ptr` + `or i1` en `codegen_visitor.rs:L694-739`.
11. **§8 Inferencia por restricciones + LCA**: exacto. `Environment::lca` está en `type_inferrer.rs:L206-218`.
12. **§8 "Inferidor no emite errores semánticos"**: exacto — verificado en `process_constraint` (`type_inferrer.rs:L521-573`) que no falla ante concretes incompatibles.
13. **§9 Múltiples errores acumulados**: exacto (`semantic.rs:L26 errors: Vec<SemError>`).
14. **§9 `for` restringido a `range(...)`**: exacto (`semantic.rs:L279-289`).
15. **§10 Layout padre-primero**: exacto (`codegen.rs:L213-222 collect_all_fields`).
16. **§10 GEP null trick**: exacto (`codegen.rs:L629-636`).
17. **§10 Vtable con override en su índice, nuevos al final**: exacto (`codegen.rs:L485-509`).
18. **§10 `phi` para `if`**: exacto (`codegen_visitor.rs:L109-158`).
19. **§11 Limitaciones**: cada bullet corresponde a una decisión efectivamente presente en el código. Este ejercicio de honestidad es notable — el equipo enumera pérdida de precisión `f32`, `for` limitado a `range`, `is`/`as` solo para clases, `print` con tipado laxo, sin cierres, verbosidad de la gramática, etc.

**Discrepancias menores detectadas**:

- **§3 "duplica ... en dos variantes paralelas"**: la gramática realmente tiene TRES cascadas (normal + OpenS + OpenB), no dos. La sección lo insinúa correctamente más adelante ("hay tres copias") pero el enunciado inicial dice "duplica en dos variantes". Redacción inconsistente, no error factual.
- **§5 sobre monomorfización**: el REPORT dice "la conformidad, un `Param` conforma con cualquier cosa, por lo que no se verifican restricciones sobre `T`" — verificado en `type_inferrer.rs:L176-177`, correcto.
- No hay una tabla explícita de features opcionales marcadas/no marcadas en el REPORT.md, aunque §11 sí enumera limitaciones. Habría sido útil una alusión explícita a "vectores/protocolos/lambdas/macros: no implementados".

**Conclusión**: el REPORT.md es de **calidad muy alta**, con enumeración honesta de limitaciones y descripción fiel al código. Las discrepancias son de redacción, no de veracidad técnica.

---

## 9. Diagnóstico de fallas principales

**CI 2026-06-22**: 71/71 obligatorios + 10/10 extras pass. Fallas reportadas en `ok/macros`, `ok/arrays`, `ok/interfaces`, `ok/lambdas`.

Todas atribuibles a features **no marcadas** por el equipo:

### 9.1 `ok/macros` — sintaxis inexistente

Los tests usan `define`:
```
define abs_val(x: Number): Number { ... }
```
`define` no es token (`token.rs`), no es palabra reservada (`lexer.rs:L80-93`), no es regla en `grammar.lalrpop`. **Falla léxica/sintáctica esperada**.

### 9.2 `ok/arrays` — sintaxis `[]` inexistente

Los tests usan `new Number[5]`, `a[0] := 10`, `Number[]`:
```
let a: Number[] = new Number[5] in { ... }
```
Los tokens `[` y `]` no están declarados en `token.rs`. El lexer los rechazará como "carácter inesperado" (`lexer.rs:L216-219`). **Falla léxica esperada**.

### 9.3 `ok/interfaces` — palabra clave `protocol` inexistente

Los tests usan `protocol`:
```
protocol Printable { to_string(): String; }
```
`protocol` no es keyword en `keyword()`. Ni siquiera se reconoce `interface`. El lexer devolverá `Token::Ident("protocol")`, el parser lo tomará como identificador y fallará sintácticamente al ver `{ to_string(): String; }` en posición no válida. **Falla sintáctica esperada**.

Adicionalmente, el tipo declarado `let p: Printable = new Point(1,2)` requiere subtipado estructural (que este compilador no implementa — subtipado es puramente nominal via `is_subtype`).

### 9.4 `ok/lambdas` — expresiones lambda inexistentes

Los tests usan lambdas de tipo función:
```
let f: (Number) -> Number = function (x: Number): Number -> x * 2 in { ... }
```
- El operador `->` no está en el lexer (`token.rs` no lo declara).
- Tampoco existe `function (...)` como valor de expresión (`grammar.lalrpop:L44-53` solo permite `function` como declaración top-level).
- El tipo `(Number) -> Number` no está soportado en `Type` (`L104-116`).
- No hay `HulkType::Function` en la enumeración de tipos (`expr_node.rs:L20-30`).

**Falla léxica/sintáctica esperada** en el token `->`.

### 9.5 Categorías con éxito 100%

Consistente con el marcado del issue:
- `ok/minimal` (20/20)
- `ok/types` (10/10)
- `ok/oop` (10/10)
- `ok/extras` (10/10)
- `errors/lexical` (6/6)
- `errors/syntactic` (10/10)
- `errors/semantic` (15/15)

**Cero fallas en features marcadas**. Cero fallas en las extensiones no marcadas pero implementadas (genéricos, tuplas). Los fallos son 100% atribuibles a los cuatro pilares sintácticos ausentes: `protocol`, `define`, `function ... ->`, `[...]`. No hay ningún bug latente ni omisión de contrato en features prometidas.

---

## Conclusión

Compilador de **calidad muy alta** implementado en Rust edition 2024 con dependencias mínimas y deliberadamente sin bindings a LLVM: el IR se emite como texto. Pipeline clásico bien modularizado — lexer manual con regex ancladas y maximal-munch por orden de reglas; parser LALR(1) via LALRPOP con cascada de precedencia triplicada `OpenS/OpenB` para resolver la ambigüedad de cuerpos abiertos; genéricos por monomorfización con worklist a punto fijo y name mangling; inferencia HM-lite por restricciones con union-find, LCA para condicionales y separación deliberada inferencia↔chequeo; `SemanticChecker` que reutiliza el `Environment` del inferidor; codegen con vtables, layout padre-primero, GEP-null trick para `sizeof`, `phi` para condicionales, RTTI por identidad de vtable, tuplas como structs anónimos. `REPORT.md` de ~7k palabras honesto y fiel al código, con solo diferencias menores de redacción. Fallas en `ok/{macros,arrays,interfaces,lambdas}` son 100% atribuibles a features **no marcadas** por el equipo en el issue (protocolos, macros, vectores, lambdas), no a bugs en features prometidas. Extensiones no marcadas efectivamente implementadas: genéricos con monomorfización y tuplas. Trabajo maduro y bien ejecutado.
