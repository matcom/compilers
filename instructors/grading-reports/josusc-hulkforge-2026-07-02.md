---
student: Ronald Cabrera, Josue J. Senarega, Jery Rodríguez, Alex Moreno
issue: 30
repo: JosuSC/HULKForge
branch: main
date: 2026-07-02
---

# Evaluación Automática — HULKForge (Ronald Cabrera, Josue J. Senarega, Jery Rodríguez, Alex Moreno)

- **Repositorio**: https://github.com/JosuSC/HULKForge.git
- **Rama**: `main`
- **Fecha de evaluación**: 2026-07-02
- **Issue del curso**: [#30](https://github.com/matcom/compilers/issues/30)
- **Última corrida de CI verificada**: 2026-06-24 (71/71 requeridos + 10/10 extras)

---

## 1. Arquitectura del compilador

HULKForge es un compilador de HULK escrito en **Rust 2021** que sigue el pipeline clásico de cuatro fases con interfaces bien delimitadas entre módulos. El árbol de fuentes se organiza en `src/lexer/`, `src/parser/`, `src/semantic/` y un único fichero `src/codegen.rs`, orquestados por `src/main.rs` (129 LOC). El total de código propio suma unas **13 462 LOC** (incluyendo tests), de las cuales aproximadamente 6 300 corresponden a lógica de compilación.

**Dependencias externas.** El manifiesto (`Cargo.toml`) declara únicamente tres crates de propósito acotado:

- `logos = "0.14"` — generador declarativo de analizadores léxicos (DFA compilado en *build-time*).
- `thiserror = "2"` — derivación de tipos de error ergonómicos.
- `indexmap = "2"` — mapas con orden de inserción estable (aunque, según se verá, en la práctica se usa `HashMap` estándar en la mayor parte del código).

**Decisión arquitectónica distintiva: transpilación a C.** En vez de construir una IR propia con una máquina virtual, o de adoptar LLVM vía `inkwell`, HULKForge **emite código C** desde el AST tipado y delega en el compilador de C del sistema (`cc`, `gcc` o `clang`, probados en ese orden) para producir el binario `./output`. Esta elección se documenta explícitamente en `REPORT.md` §10 como pragmática: reutiliza toda la *toolchain* de C (aritmética, dispatch, optimización `-O2`) a costa de exigir un `cc` en el evaluador. Es una de las pocas entregas del curso que adopta este enfoque y funciona sin dependencias runtime más allá de `libc`/`libm`.

**Contrato de interfaz.** `main.rs` implementa el *priority gating* del contrato Matcom: la fase léxica sale con exit 1 antes que la sintáctica (2), que a su vez precede a la semántica (3). El éxito (0) implica generar `output.c` y compilarlo a `./output`. Los diagnósticos se emiten a `stderr` con el formato exacto `(línea,columna) TIPO: mensaje`, respetando *spans* 1-based (definidos por `Pos` y `Span` en `src/lexer/lexer.rs:26-51`). Un fallo de backend (compilador de C ausente o fallo de `cc`) se reporta como `(0,0) SEMANTIC: backend error: ...` con exit 3 (`src/main.rs:97-100`).

---

## 2. Análisis léxico

El lexer vive en `src/lexer/lexer.rs` (447 LOC) y está construido sobre `logos`. La declaración del `enum Token` cubre todo el vocabulario de HULK: palabras clave (`let`, `if`, `while`, `for`, `function`, `type`, `new`, `inherits`, `is`, `as`, `base`, `protocol`, `extends`), literales (`Number`, `StringLit`), identificadores (`Ident`), operadores multi- y mono-carácter, y puntuación (`src/lexer/lexer.rs:113-244`).

**Puntos técnicos verificados en el código:**

- La palabra clave `protocol` acepta también `interface` como sinónimo exacto (`src/lexer/lexer.rs:140-142`), lo que permite pasar los tests del evaluador escritos con `interface`. Es un alias a nivel de lexer, no una duplicación de reglas.
- Los operadores compuestos (`+=`, `-=`, `*=`, `/=`, `%=`, `^=`, `@=`) están declarados en el lexer (`src/lexer/lexer.rs:193-200`) y luego son manejados como azúcar sintáctico en el parser (§3).
- Existe un token `InternalIdent` para identificadores que empiezan con `_` (`src/lexer/lexer.rs:176-177`); se documenta como interno para código transpilado y el parser lo rechaza en posición de usuario.
- El *string literal* usa un callback (`lex_string`, líneas 253-275) que expande escapes `\n`, `\t`, `\r`, `\0`, `\"`, `\\`; escapes desconocidos rechazan el literal completo como error léxico.
- Whitespace (`[ \t\r\n]+`) y comentarios de línea (`//[^\n]*`) se saltan vía `#[logos(skip ...)]` (líneas 114-115). **No hay comentarios de bloque** (`/* ... */`), lo cual es coherente con el manual HULK.

**Posiciones y errores.** Un `LineIndex` (líneas 59-107) traduce *byte offsets* de `logos` a coordenadas `(línea, columna)` 1-based en O(log n) vía búsqueda binaria sobre inicios de línea. Los errores léxicos se acumulan en `TokenStream::errors: Vec<LexError>` sin abortar el escaneo (líneas 344-350), y `main.rs` los enumera todos antes de salir con exit 1. El `TokenStream` mantiene un *buffer* de lookahead (`peek_n`) y garantiza un token `Eof` centinela al agotar la entrada (líneas 411-436).

**Cobertura de errores léxicos verificada**: la categoría `errors/lexical` del CI reporta 6/6 tests pasando.

---

## 3. Análisis sintáctico

El parser está en `src/parser/parser.rs` (1992 LOC) y es un **descenso recursivo escrito a mano** con escalada de precedencia. El AST tipado se declara en `src/parser/ast.rs` (384 LOC) con nodos que capturan spans en cada variante para reportes precisos.

**Cadena de precedencia (verificada en `parser.rs`).** De más baja a más alta:

`parse_expr → parse_assign → parse_or → parse_and → parse_not → parse_cmp → parse_cat → parse_add → parse_mul → parse_power → parse_unary → parse_postfix → parse_primary`

- **Asignación destructiva** (`:=`) es derecha-asociativa (`parse_assign`, líneas 259-311).
- **Compuestos** (`+=`, `-=`, etc.) se detectan en la misma capa que `:=` y se **desazucaran a nivel sintáctico**: `lhs OP= rhs` produce un AST `Assign { target, value: BinaryOp { op, left, right } }` (líneas 286-309). Confirma la afirmación de `REPORT.md` §9.6.
- **OR (`|`) y AND (`&`)** — se usa el símbolo, no las palabras clave `or`/`and` (líneas 317-360). Nótese que `|` colisiona con el separador de comprensión de vectores, lo cual se resuelve parseando el cuerpo de la comprensión a un nivel por debajo del OR (documentado como limitación menor).
- **Comparaciones no-asociativas** — solo un operador por cadena (línea 387-423).
- **Exponenciación (`^`)** es derecha-asociativa vía recursión directa (líneas 518-536).
- **Postfix** — `.field`, `.method(...)`, `[i]`, `is T`, `as T` se agrupan en `parse_postfix` (líneas 568-674), permitiendo cadenas arbitrarias.

**Interpolación de cadenas.** El parser expande `"...${e}..."` a una cadena de `@` concatenaciones dentro de `parse_primary` (líneas 700-708 y `build_interpolation` líneas 1069-1131). El *scanner* recorre balanceando `{`/`}` para hallar el cierre de `${...}` y luego re-invoca un `Parser` anidado sobre el fragmento embebido (líneas 1123-1131). Los errores del sub-parser se propagan al principal. Esto no requiere cambios en el lexer, semántico ni codegen — reutiliza `BinOp::Concat`.

**Vectores con doble sintaxis.** `parse_primary` acepta:
- `[e, e, ...]` — literal de documentación (líneas 946-985).
- `{e, e, ...}` — literal Matcom (líneas 891-944), desambiguado del bloque por el separador (`,` vs `;`).
- `[body | var in iterable]` — comprensión (líneas 961-984).
- `new T[n]` y `new T[n]{ i -> body }` — reserva con tamaño y opcionalmente con inicializador acotado (líneas 776-833).
- `T[]`, `T[][]` — dimensiones postfix en tipos (líneas 1189-1194).
- Iterable `T*` — postfix estrella sobre nombre de tipo (líneas 1180-1184).

**Manejo de errores.** El parser mantiene `Vec<ParseError>` y usa recuperación panic-mode con puntos de sincronización explícitos (`Token::Semicolon`, `Token::RBrace`, `Token::Function`, `Token::Type`, `Token::Protocol`). El helper `expect_internal` (líneas 147-182) intenta recuperación local antes de rendirse, emitiendo un token "fantasma" para no cortar el árbol. Existe un nodo `Expr::Error { span }` como placeholder de recuperación (`ast.rs:303-306`).

**Declaraciones.** `parse_program` (líneas 1451-1495) admite declaraciones en cualquier orden (`function`, `type`, `protocol`) seguidas de una expresión global obligatoria. Cada declaración tiene su propia función (`parse_func_decl`, `parse_type_decl`, `parse_protocol_decl`). Se detectan errores comunes: `extends` en lugar de `inherits` en tipos (líneas 1643-1647), `inherits` en lugar de `extends` en protocolos (líneas 1824-1827), inline bodies con bloque (`=> { ... }`, líneas 1570-1580 y 1730-1740).

**Cobertura verificada**: 10/10 tests en `errors/syntactic` del CI. Los 8 tests de `errors/syntactic` para macros y los 6 para lambdas fallan, pero eso es esperado — el parser genuinamente no reconoce ninguna de estas construcciones (§10).

---

## 4. Análisis semántico

El checker está en `src/semantic/checker.rs` (2290 LOC) y opera en **dos pasadas** sobre el AST:

1. **Predeclaración** (`predeclare_decl`, líneas 125-223): registra nombres de funciones, tipos y protocolos junto con sus aridades y firmas superficiales, para permitir referencias forward y detectar duplicados.
2. **Chequeo completo** (`check_decl` → `check_func_decl` / `check_type_decl` / `check_protocol_decl`, y luego `check_expr` sobre la expresión global): valida cuerpos, resuelve nombres, verifica conformidad de tipos y ejecuta la inferencia.

**Sistema de tipos (`SimpleType`).** Definido en `src/semantic/checker.rs:22-30`:

```rust
enum SimpleType {
    Number, String, Boolean,
    Named(String),      // tipos de usuario, protocolos, Object
    Vector(Box<SimpleType>),
}
```

Nótese que **no existe una variante `SimpleType::Iterable` en el enum**: los iterables `T*` se representan como `SimpleType::Vector(Box<T>)` con una regla especial de conformidad (véase abajo). La estrategia es sana: unifica dos categorías sintácticamente separadas en una sola en el sistema de tipos.

**Contexto** (`src/semantic/context.rs`, 812 LOC). Encapsula:

- Pilas de scopes de variables (nombre + tipo).
- Registros de funciones (con `CallableSignature`), tipos (con `TypeInfo` = `param_count`, `parent`, `attrs`, `attr_types`, `methods`) y protocolos (con `ProtocolInfo` = `extends`, `methods`).
- Builtins: funciones (`sin`, `cos`, `sqrt`, `exp`, `log`, `rand`, `print`, `range` — `context.rs:675-737`), tipos (`Number`, `String`, `Boolean`, `Object` — línea 740), constantes (`PI`, `E`, `()` — línea 748), y **protocolos builtin `Iterable` y `Enumerable`** (líneas 772-802).

**Conformidad de tipos.** La función `simple_type_conforms_to` (`context.rs:574-612`) implementa la relación `≤`:

- Identidad y subtipado nominal (walks up parent chain — línea 442-467).
- Cualquier tipo conforma a `Object` (línea 580).
- Un tipo nominal conforma a un protocolo si implementa **estructuralmente** todos sus métodos con firmas compatibles (líneas 469-493). Se verifica *también* la varianza: `callable_signature_compatible` (líneas 540-571) verifica argumentos contravariantes y retornos covariantes.
- Un tipo con método `current(): U` conforma a `T*` (representado como `Vector<T>`) si `U ≤ T` (líneas 601-609). **Esta es la conformidad iterable estructural que menciona el reporte**; permite pasar generadores donde se espera un iterable.

**LCA (Lowest Common Ancestor).** `context.rs:618-642` implementa el join de dos tipos: se sube por la cadena de padres del primero buscando el primer ancestro que sea subtipo del segundo. Los vectores hacen LCA elemento a elemento; los tipos base (`Number`/`String`/`Boolean`) solo se unen consigo mismos, degenerando a `Object` en otros casos. **El LCA se usa para tipar las ramas de `if`/`elif`/`else` uniformemente** (`checker.rs:1497-1508`), evitando el rechazo estricto que da la comparación por igualdad.

**Síntesis de protocolos (A.9.5).** `SemanticChecker::synthesize_param_protocols` (`checker.rs:84-111`) recorre los parámetros sin anotar de funciones y métodos. Si un parámetro `x` se usa estructuralmente como receptor de método (`x.f()`), se crea un protocolo `__SynthN` con los métodos requeridos y se liga `x: __SynthN`. Los tipos de retorno de los métodos sintetizados se infieren del contexto operador donde se consumen (`String` si con `@`/`@@`, `Number` si aritmético, `None` = "any" en otro caso). Estos `None` no imponen restricciones — mantienen permisiva la conformidad.

**Overriding y varianza.** `check_inherited_method_overrides` (`checker.rs:574-608`) exige que los overrides mantengan **firma exacta** (`callable_signature_exactly_matches`, líneas 610-616). Es una restricción más fuerte que la varianza usual (contravarianza argumentos + covarianza retorno), pero HULK así lo pide y el reporte lo documenta. Los tests semánticos confirman este comportamiento (15/15 en `errors/semantic`).

**Otros chequeos verificables:**
- Redefinición de funciones/tipos/protocolos, y colisión con builtins (líneas 148-223).
- Ciclos de herencia en tipos (`type_inheritance_has_cycle`, líneas 700-712) y en protocolos (líneas 715-727).
- Tipo padre debe existir y no ser protocolo (`check_inherits_clause`, líneas 661-697).
- `base(...)` requiere estar dentro de un método con padre y firma coincidente (`checker.rs:871-912`).
- `self` fuera de método → error (`checker.rs:759-763`).
- Uso de identificadores no definidos, aridad incorrecta en llamadas, tipos no definidos en anotaciones.

---

## 5. Backend / Codegen — Transpilación a C en profundidad

El backend está enteramente en `src/codegen.rs` (911 LOC). Ésta es la sección técnicamente más interesante del proyecto por la coherencia del modelo de runtime elegido.

### 5.1. Modelo runtime: tagged `Value`

Todo valor HULK en tiempo de ejecución es un `struct` C etiquetado (`codegen.rs:826`):

```c
typedef struct { int tag; double num; char* str; int b; Obj* obj; Vec* vec; } Value;
```

Con tags `TAG_NUM = 0`, `TAG_STR = 1`, `TAG_BOOL = 2`, `TAG_OBJ = 3`, `TAG_VEC = 4` (líneas 818-822). Es una unión discriminada gorda (todos los campos coexisten) — se sacrifica ~40 bytes por valor a cambio de simplicidad total en las conversiones y de no depender de compilación por tipos. Los constructores `mk_num`, `mk_bool`, `mk_str`, `mk_vec` (líneas 830-845) crean cada variante con los otros campos en cero.

### 5.2. Layout de objetos y slot maps globales

Cada tipo de usuario en HULK se compila a un `Obj` (línea 827):

```c
struct Obj { int type_id; Value* fields; };
```

Los atributos se indexan por un **mapa global nombre→slot** (`attr_slots: HashMap<String, usize>`). El slot se asigna al primer encuentro de cada nombre de atributo durante la construcción de `Codegen::new` (`codegen.rs:73-76`) y es **compartido entre todos los tipos**. Igualmente los métodos: `method_slots: HashMap<String, usize>` (líneas 77-80) asigna un slot global por nombre de método. Los tres nombres del protocolo iterador (`next`, `current`, `iter`) se reservan primero para que el `for` loop pueda probar cualquier vtable en esas posiciones (líneas 61-64).

Este *layout* — slots globales compartidos, no por-tipo — es una decisión de simplicidad significativa: implica que si dos tipos tienen atributos o métodos homónimos, comparten slot en la vtable/tabla de atributos. Funciona porque el chequeo estático ya validó que se accede al slot correcto para cada tipo, y porque cada objeto reserva `NUM_ATTR_SLOTS` posiciones aunque no las use todas (línea 336). El costo es memoria per-instance proporcional al número **total** de atributos declarados en el programa, no al del tipo concreto.

### 5.3. Vtables

Cada tipo tiene una entrada `vtables[type_id][method_slot]` = puntero a función C (líneas 112-113). La inicialización ocurre en `init_tables` (líneas 156-177): para cada tipo y cada método declarado en el `method_slots` global, se resuelve la implementación más derivada subiendo por la cadena de herencia (`resolve_method`, líneas 190-205). Los slots donde el tipo no implementa el método quedan en `NULL` — el `for` loop y el operador overloading verifican esto en runtime.

### 5.4. Constructores e inicialización padre-primero

`hulk_new_<T>` (líneas 333-339) hace `malloc(Obj)`, asigna `type_id`, `calloc` los fields, e invoca `hulk_initall_<T>`. El `initall` (líneas 297-330) es donde ocurre la inicialización:

1. Se computan los argumentos de `inherits(...)` como expresiones HULK.
2. Se llama al `initall` del padre con esos argumentos (línea 320).
3. Se inicializan los atributos propios en orden de declaración (líneas 322-325).

Este orden padre-primero es correcto para inicializaciones que dependen de atributos heredados.

### 5.5. Dispatch dinámico y `is`/`as`

- `x.m(args)` se compila a `vtables[x.obj->type_id][SLOT_m](x, argv)` (líneas 509-527). No hay chequeo runtime de que el slot no sea NULL en el caso general; en el caso especial de `size()` sobre vectores hay un fallback (`vec_size(...)`, línea 514-519).
- `x is T` para tipos de usuario usa `hulk_is` (líneas 116-122): camina la cadena `parent_id[id]` hasta encontrar `target` o llegar a `-1`. Para builtins (`Number`, `String`, `Boolean`) compara `.tag` directamente (líneas 552-560).
- `x as T` es **identidad** en runtime (línea 563): la seguridad la aportó el chequeo estático.
- `base(args)` (líneas 529-544) invoca directamente `hulk_m_<parent>_<method>` resolviendo el padre en compile-time; no pasa por vtable.

### 5.6. Iteración uniforme

`gen_iter_loop` (líneas 633-682) unifica tres casos:

1. **`range(a, b)`** se reconoce sintácticamente y se baja a un `for (double i = a; i < b; i += 1.0)` puro (líneas 634-653), sin objeto iterador.
2. **Vectores** (`tag == TAG_VEC`) se iteran por índice sobre `vec->data` (línea 672).
3. **Objetos con protocolo iterador** llaman a `next`/`current` por vtable. Si el objeto no implementa `next` pero sí `iter`, se llama a `iter()` primero (líneas 662-665) — implementa el fallback `Enumerable` → `Iterable`.

### 5.7. Sobrecarga de operadores y compound assignment en codegen

`gen_binop` (líneas 745-782): si el operador tiene un método asociado y el codegen ha visto algún tipo que declare ese método, se emite un branch runtime:

```c
Value t = (a.tag == TAG_OBJ) ? vtables[a.obj->type_id][SLOT_plus](a, argb) : hulk_add(a, b);
```

Esto significa que **el dispatch de operador es siempre por-runtime cuando existe** un método candidato en algún tipo del programa. Los números/strings preservan el fast-path builtin. La afirmación de `REPORT.md` §9.5 sobre "sin coste para código puramente numérico" es aproximada — el branch existe estáticamente, pero es una comparación de tag que el CPU predice bien.

El compound assignment ya se resolvió en parser (§3), así que el codegen no necesita hacer nada especial.

### 5.8. Runtime C (RUNTIME_PREAMBLE)

Aproximadamente 100 líneas de C inline (líneas 813-910+) que definen `Value`, `Obj`, `Vec`, constructores, coerciones (`val_to_str`, `num_to_str`), operadores aritméticos/lógicos/de comparación (`hulk_add`, `hulk_eq`, `hulk_concat`, etc.), `hulk_print`, y las primitivas de vector (`mk_vec`, `vec_lit`, `vec_index`, `vec_set`, `vec_size`, `vec_append`).

**Ausencia deliberada de GC** — se usa `malloc/calloc/realloc` sin `free` (documentado en `REPORT.md` §8.7 como *malloc-and-leak*). Para programas de prueba es suficiente; para código de producción no. El reporte lo enuncia como trabajo futuro.

**Sin bounds-checking** en `vec_index` (línea 846): un índice fuera de rango es UB (como en C). Coherente con la elección de transpilar a C sin instrumentar.

---

## 6. Features implementadas — verificación

Tras revisar código fuente contra las categorías del CI y la afirmaciones del reporte:

| Feature (§ manual)                | Marcado en issue | AST | Semántica | Codegen | CI       |
|-----------------------------------|:-:|:-:|:-:|:-:|:--------:|
| Núcleo A.1-A.7 (`ok/minimal`)      | ✔️ | ✔️ | ✔️ | ✔️ | 20/20    |
| Tipado A.8 (`ok/types`)           | ✔️ | ✔️ | ✔️ | ✔️ | 10/10    |
| Herencia + polimorfismo + `is`/`as` (`ok/oop`) | ✔️ | ✔️ | ✔️ | ✔️ | 10/10    |
| Iterables A.11 (`ok/extras`)        | ✔️ | ✔️ | ✔️ | ✔️ | Incluido |
| Vectores A.12                      | ✔️ | ✔️ | ✔️ | ✔️ | Incluido |
| Protocolos A.10                    | ✔️ | ✔️ | ✔️ | ✔️ (borrados en runtime) | Incluido |
| Inferencia A.9 (LCA + síntesis)    | — (implícito por reporte) | ✔️ | ✔️ | ✔️ | Cubierto |
| Sobrecarga de operadores           | — (extensión) | ✔️ | ✔️ | ✔️ | Ejemplos |
| Asignación compuesta               | — (extensión) | ✔️ (desazúcar) | — | — | Ejemplos |
| Interpolación de cadenas           | — (extensión) | ✔️ (desazúcar) | — | — | Ejemplos |
| Lambdas / Functors A.13            | ✗ | ✗ | ✗ | ✗ | 0/6 fail |
| Macros A.14                        | ✗ | ✗ | ✗ | ✗ | 0/8 fail |

Los ejemplos `examples/operator_overloading.hulk`, `examples/compound_assignment.hulk`, `examples/string_interpolation.hulk`, `examples/inference_protocols.hulk` y `examples/vectors.hulk` son programas end-to-end que ejercitan cada extensión — están limpiamente escritos y las salidas esperadas están anotadas como comentarios inline.

---

## 7. Discrepancias entre REPORT.md y el código

El reporte es notablemente honesto — la mayoría de las afirmaciones son verificables en el código. Los desajustes encontrados son menores:

**Menores / documentación:**
- El reporte menciona `indexmap` como dependencia relevante para determinismo (§2). En el código, `codegen.rs` importa `std::collections::HashMap`, no `indexmap::IndexMap`; el orden de iteración de `attr_slots` y `method_slots` es determinista solo por la fase de inserción (los slots ya fueron asignados por número). El determinismo real no depende del tipo de mapa.
- El reporte afirma que la fase léxica emite todos los errores y sale con 1 (§3). Verificado: `main.rs:60-66` usa `tokenize_all` para obtener todos los errores léxicos antes de salir.
- El reporte cita "397 tests unitarios" (§11). No verifiqué el número exacto, pero los ficheros `src/lexer/test.rs` (1858 LOC), `src/parser/tests.rs` (781 LOC) y `src/semantic/tests.rs` (2741 LOC) suman una batería sustancial de pruebas.

**Subclaims verificables al alza:**
- El reporte describe la inferencia como "bottom-up best-effort" con tres mecanismos (§9.1). El código lo confirma: `infer_simple_type` (`checker.rs:1443-1634`) recorre la expresión, `lowest_common_ancestor` (`context.rs:618-642`) implementa el LCA, y `synthesize_param_protocols` (`checker.rs:84-111`) la síntesis.
- La conformidad iterable estructural (§7 del reporte) está implementada en `context.rs:601-609` — un tipo con `current(): U` conforma a `T*` si `U ≤ T`.
- La sobrecarga de operadores despacha por tipo del operando izquierdo (§9.5, límite documentado): confirmado en `checker.rs:924-939` (semántica) y `codegen.rs:769-780` (codegen). `2 + v` con `v` un `Vec2` usa el builtin numérico y falla en runtime si `v` no fuera número — el chequeo estático detecta el mismatch antes.

**Sin discrepancias significativas** — el reporte se corresponde con el código.

---

## 8. Fallas: por qué macros y lambdas no pasan (correcto)

Las categorías `errors/syntactic` para macros (8/8 fallando en pruebas específicas de macros) y `ok/lambdas` (6/6 fallando) son coherentes con lo declarado:

- **Búsqueda exhaustiva en el código fuente**: `grep -i "lambda\|macro"` sobre todo `src/` solo devuelve dos comentarios en `src/lexer/lexer.rs` que mencionan la palabra "lambda" al describir `=>` y `->`, y **una sola** ocurrencia de "macros" en un comentario docstring en `src/semantic/checker.rs:1317` ("Validate a call to an identifier: variables, functions, macros or builtins") — un residuo de plantilla, no una implementación.
- **AST** (`src/parser/ast.rs`) no declara ninguna variante `Lambda`, `Function` como expresión, `Macro`, `Define`, ni construcción de primera clase equivalente. Las 25 variantes de `Expr` cubren exactamente lo enumerado en §3.
- **Parser** (`src/parser/parser.rs`) no tiene ninguna rama en `parse_primary` para `lambda`, `\`, o palabra clave equivalente. La única cosa "lambda-ish" es el inicializador acotado `new T[n]{ i -> body }`, que no es un valor de primera clase — es una forma cerrada solo válida en esa posición sintáctica.
- **Codegen** naturalmente no tiene machinery de closures ni ambientes capturados.

El issue #30 **no marca** macros ni lambdas como implementadas. El reporte (§9 y §12) las declara explícitamente como decisión consciente de no-implementación. La calificación es congruente: no se pierden puntos por no implementar features no marcados.

Ninguna otra categoría del CI falla.

---

## 9. Fortalezas destacadas

1. **Coherencia arquitectónica.** La transpilación a C con tagged `Value` + vtables globales es una elección con muy pocas piezas en fricción entre sí. Los extras (operator overloading, iterables, protocolos) se implementan sin casos especiales en codegen porque el dispatch dinámico uniforme ya los soporta.
2. **Extensiones como desazúcar sintáctico.** Compound assignment, string interpolation y operator overloading se implementan sin tocar el modelo runtime — el parser los reduce a construcciones existentes. Este es el estilo correcto para features "de conveniencia".
3. **Manejo de errores robusto en el parser.** Recuperación panic-mode con recovery points explícitos, mensajes con span, y un nodo `Expr::Error` como placeholder que permite continuar validando el resto del programa.
4. **Documentación con doc-comments.** Cada módulo Rust tiene `//!` describiendo el rol; cada función pública tiene `///` con la gramática cuando corresponde. Facilita la revisión.
5. **Baja dependencia externa.** Solo `logos`, `thiserror`, `indexmap` — todos crates estables. El binario resultante depende solo de `libc`/`libm`.

---

## 10. Debilidades y observaciones

1. **Sin bounds-checking en vectores.** `vec_index` no verifica que el índice esté en rango; un `a[100]` sobre un vector de 5 elementos es UB (leerá memoria adyacente). Trabajo futuro documentado, pero un `assert(i < v.vec->len)` en runtime sería una línea.
2. **Sin recolección de basura.** Programas de larga vida gotearían memoria. Documentado como *malloc-and-leak* con GC como trabajo futuro.
3. **`Value` es "gordo".** ~40 bytes por valor (todos los campos coexisten). Una unión C real (`union { double n; char* s; Obj* o; Vec* v; }`) con el tag arriba reduciría el footprint a ~16 bytes. Optimización posible sin cambiar la interfaz.
4. **Slots de atributos globales.** Cada objeto reserva `NUM_ATTR_SLOTS` posiciones aunque solo use un puñado. Para programas con muchos tipos con nombres de atributo distintos, el `sizeof(Obj->fields)` crece. Un layout por-tipo (slots locales) es más eficiente pero requiere más código.
5. **`::size()` como caso especial.** El codegen tiene un branch especial para `size()` sobre vectores (`codegen.rs:514-519`). Es sensato pero fragiliza levemente el modelo uniforme.
6. **Los operadores lógicos (`&`, `|`) no soportan sobrecarga.** `BinOp::And | BinOp::Or => return None` en `operator_method` (`ast.rs:362`) — decisión coherente con la semántica de corto-circuito pero no documentada como límite en el reporte.
7. **La inferencia no reporta "debe tiparse explícitamente".** Subreporta por solidez (documentado). En la práctica pasa los tests porque la síntesis de protocolos cubre los casos típicos.

---

## 11. Conclusión

HULKForge es una entrega **completa, técnicamente sólida y arquitectónicamente coherente**. Cubre las categorías del contrato (71/71 requeridos + 10/10 extras a fecha de 2026-06-24) con código legible, bien tipado por Rust y con una decisión de backend distintiva —transpilación a C con tagged `Value` y vtables globales— que reutiliza sensatamente la *toolchain* de C en vez de reinventar la rueda con una VM propia.

Las extensiones declaradas (sobrecarga de operadores, asignación compuesta, interpolación de cadenas) están **verificadas end-to-end**: existen en la gramática, en el chequeo semántico cuando corresponde, y en el codegen. La implementación de protocolos e iterables va más allá del mínimo — la síntesis de protocolos (A.9.5) y la conformidad estructural iterable son extensiones interesantes sobre el manual.

El reporte técnico (`REPORT.md`, 808 líneas) es honesto: describe con precisión lo implementado, marca sus límites (sin GC, sin bounds-check, sin lambdas ni macros), y justifica las decisiones. Las discrepancias con el código son mínimas y no comprometen la validez del análisis.

Las ausencias (lambdas A.13, macros A.14) son declaradas explícitamente en el issue #30 y en el reporte como no implementadas, y son consistentes con lo que muestra el CI. No comprometen la calificación porque no fueron marcados como features entregados.

En comparación con otras entregas del curso —muchas basadas en LLVM, algunas con QBE, y varias con IRs propias— HULKForge se distingue por la **simplicidad del modelo y la disciplina de reutilizar mecanismos**: el mismo dispatch por vtable soporta métodos, iteradores y operadores sobrecargados; el mismo runtime de vectores soporta las dos sintaxis (Matcom y documentación); el mismo desazúcar sintáctico habilita compound assignment y string interpolation. Es un ejemplo pedagógico útil de que un compilador no necesita ser barroco para ser correcto y expresivo.
