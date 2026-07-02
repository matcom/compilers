---
student: mauricio04mh
team: Camilo Humberto Perez Fleita, Mauricio Medina Hernandez, Guillermo Hughes Cardona
issue: 36
repo: https://github.com/mauricio04mh/hulk-compiler
branch: main
date: 2026-07-02
---

# Reporte de calificación — mauricio04mh/hulk-compiler

## 1. Descripción arquitectónica

El proyecto es un compilador para HULK escrito íntegramente en **Rust 2024** (resolver 3) que emite ejecutables nativos x86-64 Linux a través de LLVM IR compilado con `clang`. Está organizado como un `cargo workspace` con **8 crates** cuyas responsabilidades siguen la separación clásica de un pipeline de compilación (`Cargo.toml`, `Cargo.lock`):

- `hulk-lexgen` — generador de lexers dirigido por especificaciones `.lx` **hecho a mano**.
- `hulk-parsegen` — generador de parsers LL(1) con extensión Pratt para expresiones, dirigido por gramáticas `.gx` propias.
- `hulk-frontend` — orquesta lexer + parser, expone cinco pipelines cacheadas vía `OnceLock` (`expr`, `functions`, `control`, `types`, `full`) y define el AST público.
- `hulk-sema` — análisis semántico: chequeo de tipos, inferencia multi-pasada por fixpoint, conformancia estructural de protocolos, expansión de macros.
- `hulk-ir` — representación intermedia (`IrProgram`, `IrFunction`, `IrInstr`, `IrType`).
- `hulk-lower` — lowering desde HIR (semántica) a IR con resolución de slots de vtable y protocolos.
- `hulk-codegen-llvm` — generación de LLVM IR textual (`.ll`).
- `hulk-driver` — CLI `hulkc` que hilvana todo el pipeline y llama a `clang` para producir el ejecutable.

El runtime está en **C puro** (`runtime/hulk_runtime.c`, ~440 líneas + header) y se enlaza como biblioteca estática. Los tests unitarios cubren cada crate: **529 pruebas verdes** en `cargo test --workspace --all-targets` (0 fallos). La CI del equipo reporta **71/71 obligatorios + 10/10 extras** verdes al 2026-06-23.

El diseño destaca por dos decisiones fuertes: (a) implementar generadores propios de lexer y parser en lugar de usar `pest`/`lalrpop`/`nom`, y (b) delegar toda la ABI de objetos a un runtime C con vtables uniformes cuyo primer campo es siempre `HulkVTable*`, incluyendo rangos y vectores.

## 2. Lexer — `hulk-lexgen`

El lexer se genera desde archivos `.lx` (por ejemplo `crates/hulk-parsegen/testdata/specs/hulk_types.lx`, que es el spec efectivo que usa el driver). El crate se estructura en tres módulos:

- `spec/` — tipos `LexerSpec`, `ExactRule`, `IdentifierRule`, `NumberRule`, `StringRule`, `TokenKindDef`.
- `lx/` — parser del propio DSL `.lx` (`LxLexer`, `LxParser`).
- `runtime/` — scanner `lex_hulk(input, spec) -> Vec<Token>` con manejo de posiciones y errores léxicos con `Span`.

Los tokens exactos definidos en `hulk_types.lx` no siguen las convenciones sugeridas por REPORT.md — ver §9. Los operadores reales son:

- `symbol "^" POW` (potencia)
- `symbol "&" AND`, `symbol "|" OR`, `symbol "!" NOT`
- `symbol "=>" ARROW` (para cuerpos de funciones)
- `symbol "->" FUNCARROW` (para tipos functor)
- `symbol "@" CONCAT`, `symbol "@@" CONCATSP`, `symbol ":=" DASSIGN`

Las palabras clave están declaradas (`keyword "let"`, `keyword "function"`, `keyword "type"`, `keyword "protocol"`, `keyword "inherits"`, `keyword "extends"`, `keyword "is"`, `keyword "as"`, `keyword "match"`, `keyword "def"`, etc.). El lexer reconoce números (`NumberRule`), strings con escapes (`StringRule` — soporta `\"`, `\n`, `\t`, `\\`) e identificadores. Los errores léxicos (carácter inesperado, string sin cerrar) son detectados por el driver mediante el patrón textual en el mensaje y provocan **exit code 1**.

## 3. Parser — `hulk-parsegen`

Es un generador LL(1) con "gancho" Pratt para expresiones. La gramática efectiva vive en `crates/hulk-parsegen/testdata/grammars/hulk_types.gx` (136 líneas). Modula reglas para tipos, protocolos, functor types, patrones y match. El driver invoca `parse_hulk_types_program` desde `hulk-frontend`.

**Pratt parser** (`crates/hulk-parsegen/src/runtime/pratt.rs`): configurado por `PrattConfig` con campos para `match_kw`, `wildcard`, `is_kw`, `as_kw` y toda la tabla de operadores. `MAX_PARSE_DEPTH = 512`. Precedencias asignadas por `hulk_pratt_parser()` en `hulk-frontend/src/lib.rs`:

| Nivel | Ops                        | Asociatividad |
|-------|----------------------------|---------------|
| 0     | `:=`                       | derecha       |
| 1     | `\|` (or)                  | izquierda     |
| 2     | `&` (and)                  | izquierda     |
| 3     | `==`, `!=`                 | izquierda     |
| 4     | `<`, `>`, `<=`, `>=`       | izquierda     |
| 5     | `@`, `@@`                  | izquierda     |
| 6     | `+`, `-`                   | izquierda     |
| 7     | `*`, `/`, `%`              | izquierda     |
| 8     | `^` (pow)                  | derecha       |

La gramática soporta reglas específicas para: `TypeExpr -> LPAREN FunctorTypeParams RPAREN FUNCARROW TypeExpr` (tipos functor con `->`), `FunctionBody` con ambos `ARROW` (`=>`) y `FUNCARROW` (para permitir estilos alternos), y `OperatorExpr -> MATCH` para integrar `match` como expresión. Los errores sintácticos producen **exit code 2**.

## 4. Análisis semántico — `hulk-sema`

Este es el crate más denso: `crates/hulk-sema/src/hir_builder.rs` tiene **3123 líneas**. Su núcleo es un `HirBuilder` que ejecuta múltiples pasadas hasta punto fijo para inferir tipos.

**Sistema de tipos** (`types.rs`, 40 líneas):

```rust
enum Type {
    Number, String, Boolean, Object, UserType(String),
    Vector(Box<Type>), Iterable(Box<Type>),
    Functor { params: Vec<Type>, ret: Box<Type> },
    Unknown,
}
```

**Piezas destacadas**:

- **Inferencia multi-pasada**: recorre el programa hasta que ningún tipo `Unknown` cambia. Sirve para resolver mutuas dependencias entre funciones y métodos.
- **Conformancia estructural de protocolos**: `implicitly_conforms_to_protocol` chequea si un tipo satisface un protocolo por su firma pública, sin declaración explícita.
- **`analyze_match`** — verifica exhaustividad y produce `SemanticError::NonExhaustiveMatch` cuando el patrón no cubre todos los tipos posibles.
- **Expansión de macros in-line** (`inline_macro`, ~línea 2529): `def`s se expanden por sustitución call-by-name usando `substitute_expr` con `HashMap<String, Expr>`.
- **Chequeos de herencia**: detección de ciclos (`CircularInheritance`), visibilidad de atributos (`AttributeIsPrivate`), y compatibilidad de firmas al sobreescribir (`ProtocolMethodSignatureMismatch`).

**Builtins** (`builtins.rs`, 96 líneas): `print`, `sqrt`, `sin`, `cos`, `exp`, `log`, `rand`, `range`, `abs`, `floor`, `ceil`, `round`, `min`, `max`. Constantes: `PI`, `E`. **No aparece `pow`** aunque el reporte lo lista — la potenciación existe solo como operador binario `^`.

**Errores semánticos**: `SemanticError` incluye `UndefinedVariable`, `UndefinedFunction`, `UndefinedMethod`, `TypeMismatch`, `MissingProtocolMethod`, `NonExhaustiveMatch`, `AttributeIsPrivate`, `CircularInheritance`, entre otros. Cada uno lleva `Span`. El driver mapea a **exit code 3**.

## 5. IR y lowering — `hulk-ir` + `hulk-lower`

**IR** (`hulk-ir/src/lib.rs`, 673 líneas): representación de tres direcciones. `IrProgram` agrupa `IrData` (constantes, strings, vtables), `IrFunction` (bloques básicos + firmas) y una tabla de tipos. `IrInstr` cubre todas las operaciones esperadas: aritméticas, `VirtualCall`, `StaticCall`, `BaseCall` (llamada al método del padre), `MakeClosure`/`ClosureCall`, `TypeTest`, `TypeCast`, `NewVector`, `VectorGet`/`Set`/`Push`/`Len`, `GetAttr`/`SetAttr`.

**Lowering** (`hulk-lower/src/lib.rs`): `LoweringContext` traduce el HIR ya tipado a IR. Detalles importantes:

- Los tipos `Iterable` y `Vector` reciben pre-siembra de slots: **slot 0 = `next`**, **slot 1 = `current`**. Cualquier usuario que use `for x in expr` se convierte en llamadas polimórficas a estos dos slots.
- `populate_protocol_slots` resuelve las tablas de método respetando herencia, garantizando que un tipo hijo herede el mismo slot para métodos no sobreescritos.

## 6. Codegen — `hulk-codegen-llvm`

Emite LLVM IR textual (`.ll`) con `format!`; no depende de `inkwell`. Tipos ABI clave:

- `%HulkString = type { i64, ptr }` — longitud + puntero a bytes.
- `%HulkVTable = type { i64, ptr, i64, ptr, ptr }` — `type_id`, `parent`, `method_count`, `methods*`, `type_name*`.
- Todos los objetos comienzan con `HulkVTable*` para permitir `hulk_object_method` uniforme.

Destaca por:

- Guardas de división y módulo: emite un `if divisor == 0` que llama a `hulk_runtime_error`.
- Potenciación via `call double @hulk_pow(double, double)`.
- Despacho virtual vía `hulk_object_method(obj, slot)`.
- Rutas especiales para receptores `Iterable`, `Vector`, `String` (métodos como `.size()`) y protocolos.
- Declara toda la superficie del runtime (`declare` en cabecera del `.ll`).

## 7. Runtime en C

`runtime/hulk_runtime.c` (441 líneas) y `runtime/hulk_runtime.h`. Piezas destacables:

- **Arena bump allocator de 64 MB** con redirección `malloc → arena`. Simplifica al máximo la gestión (no hay `free` explícito). El programa termina antes de fragmentar seriamente.
- **Objetos vtable-uniformes**: `hulk_alloc_object`, `hulk_object_method` (indexa `vtable->methods[slot]`), `hulk_object_is` (recorre la cadena `parent` para chequear la relación), `hulk_object_as` (aborta si el cast es imposible).
- **Getters/setters tipados** por atributo: `hulk_object_set_number/bool/string/object` y sus getters, usando `memcpy` para preservar la alineación.
- **Vectores y rangos** llevan una **`HulkVTable` estática** cada uno con `next`/`current` en slots 0 y 1 — esto es lo que hace que `for` polimórfico funcione uniformemente.
- **Closures** (`HulkClosure`): puntero a función + arreglo flexible de capturas (`captures[]` C99). `hulk_closure_alloc/set/get` gestionan la reserva.
- **Strings**: `hulk_string_concat`, `hulk_string_sub`, `hulk_string_len`, `hulk_string_eq/equals`, `hulk_string_from_number/bool`.
- **Math**: `hulk_sqrt`, `hulk_sin`, `hulk_cos`, `hulk_exp`, `hulk_log`, `hulk_pow`, `hulk_rand`, `hulk_abs`, `hulk_floor`, `hulk_ceil`, `hulk_round`, `hulk_min`, `hulk_max`.

`hulk_runtime_error` imprime el mensaje y llama a `exit(1)`. `hulk_abort` es una variante para errores irrecuperables (typecheck fallido).

## 8. Features opcionales

Todos los opcionales marcados en el issue #36 están implementados y verificados por compilación real:

- **Tipos + herencia + `self`**: `type Animal(name: String) { name = name; speak() => "..." }`, `type Dog inherits Animal("dog") { speak() => "woof" }`. La inicialización de padres con argumentos explícitos funciona (probado). El passthrough sin argumentos (`inherits Animal` sin paréntesis) **exige aridad compatible** — ver §9.
- **`is` y `as`**: emiten `TypeTest` y `TypeCast` (IR) que se traducen a `hulk_object_is`/`hulk_object_as`. Si el cast falla, aborta en runtime.
- **Iterables (`T*`)**: el receptor solo necesita implementar los métodos `next` y `current` que caen en los slots 0 y 1 pre-sembrados. Basta con conformar estructuralmente a `Iterable`.
- **Vectores**: literales explícitos `[1, 2, 3]`, comprensiones `[x^2 | x in range(0, 10)]`, indexación `v[i]`, tamaño `v.size()`.
- **Protocolos con extends estructural**: `protocol Equatable extends Hashable { ... }` y conformancia sin declaración explícita del tipo.
- **Functors + lambdas**: `let f = (x) => x * 2 in f(5)` y `filter: (Number) -> Boolean` como firma de parámetro.
- **Macros**: `def repeat($iter, n, *expr) { ... }` con soporte para argumentos especiales `*`, `@`, `$`. Se expanden in-line en el HIR mediante sustitución call-by-name.
- **Pattern matching (`match`)** con variantes: `Wildcard`, `TypePattern`, `Literal`, `Binding`. El desugaring produce cadenas de `If + Let + TypeTest + TypeCast + Binary` (para literales).

## 9. Exactitud del reporte

`REPORT.md` (458 líneas, ~4161 palabras) es un documento técnico muy elaborado. Sin embargo, **contiene varias discrepancias factuales con el código actual** que hay que registrar:

1. **Operadores léxicos**. El reporte afirma que se usan `**` para potencia y `and`/`or`/`not` para lógicos. El spec `hulk_types.lx` implementa `^` para potencia y `&`/`|`/`!` para lógicos. Ninguna palabra clave `and`, `or`, `not` está declarada. Los tests del propio proyecto siguen la sintaxis con `^` y `&`/`|`/`!`.

2. **Dirección de las flechas**. El reporte confunde el uso de `=>` y `->`. En la práctica: `=>` (`ARROW`) es para **cuerpos de función/lambda**; `->` (`FUNCARROW`) es para **tipos functor** (`(Number) -> Boolean`). La gramática (`hulk_types.gx`) es explícita en esto.

3. **Builtin `pow`**. El reporte menciona `pow` en la lista de builtins. Revisando `crates/hulk-sema/src/builtins.rs` (96 líneas) no aparece; la potenciación existe únicamente como operador binario `^` que en codegen llama a `hulk_pow` del runtime.

4. **Passthrough de constructor**. El reporte sugiere que `type Dog inherits Animal { ... }` (sin argumentos) hace passthrough automático de los parámetros del padre. Al probarlo el compilador emite error de aridad — no es passthrough. Sí funciona el patrón `type Dog inherits Animal("dog") { ... }` con argumentos explícitos.

5. **Referencias al `Makefile`**. El `Makefile` referencia `tests/hulk/run_tests.sh` pero ese directorio no existe. La CI real usa `cargo test --workspace --all-targets --locked` (que sí pasa, 529/529). No es un problema funcional pero denota mantenimiento incompleto.

Fuera de estos puntos, el reporte **describe correctamente** la arquitectura del pipeline, el rol de cada crate, las decisiones de diseño (arena, vtables uniformes, generadores propios), y los tipos ABI del runtime.

## 10. Diagnóstico de fallas principales

**Fortalezas**:

- Cobertura completa de features (obligatorias y todas las opcionales) verificada por compilación real y por 71/71 + 10/10 tests.
- Arquitectura sólida y modular: separación limpia frontend/sema/ir/lower/codegen con crates independientes que se pueden testear aisladamente.
- **Generador propio de lexer y parser** (`hulk-lexgen`, `hulk-parsegen`) — decisión ambiciosa que se paga en control fino sobre la sintaxis y en no arrastrar dependencias.
- **ABI de objetos elegante**: primer campo siempre `HulkVTable*` para todo (objetos, vectores, rangos). Un solo `hulk_object_method` sirve para todo tipo de despacho virtual, incluyendo iteradores.
- **529 tests unitarios verdes** en todo el workspace, alta cobertura por crate.
- Runtime en C conciso (~440 LOC) y explícito; arena bump allocator es una simplificación pragmática para un compilador de curso.

**Puntos débiles / mejorables**:

- El reporte contiene **inexactitudes** que no reflejan el estado actual del código (operadores, `pow`, passthrough) — probablemente residuo de versiones previas del compilador.
- **Sin `free`**: la arena de 64 MB nunca libera memoria. Aceptable para programas pequeños, pero cualquier programa que asigne más de 64 MB abortará.
- El `Makefile` referencia scripts inexistentes; la CI usa `cargo test` directo.
- El `hir_builder.rs` de 3123 líneas concentra demasiada complejidad; sería un candidato natural para dividir en submódulos por fase (declaración, inferencia, chequeo, macros).
- La inferencia por fixpoint no reporta cuándo un tipo permanece `Unknown` porque el programa es genuinamente ambiguo — cae en un error genérico.

**Veredicto**: proyecto sobresaliente. La ejecución técnica está por encima del promedio: implementaron generadores propios, un runtime C consistente y todas las features. Las discrepancias del reporte son documentales, no funcionales.
