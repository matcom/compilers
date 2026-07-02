---
repo: https://github.com/DayanCabrera2003/hulk_compiler
branch: main
issue: 24
team: Dayan Cabrera Corvo (C312)
date: 2026-07-02
tests_snapshot: 2026-06-14
tests_required: 71/71
tests_extras: 10/10
tests_failed_bonus: 1 (ok/macros/define_loop)
---

# Reporte técnico — hulk_compiler (Dayan Cabrera Corvo)

## 1. Contexto y alcance

La entrega corresponde al equipo unipersonal C312 y consiste en un compilador
completo del lenguaje HULK escrito en Rust (edición 2021) que produce
ejecutables nativos mediante LLVM 17 vía el binding `inkwell 0.4`. El
repositorio se estructura como un workspace de Cargo con quince crates, un
runtime en C con recolector de basura propio, y una suite de pruebas que
supera holgadamente las categorías obligatorias del contrato de evaluación:
71/71 requeridos (`ok/minimal`, `ok/types`, `ok/oop`, `errors/lexical`,
`errors/syntactic`, `errors/semantic`) y 10/10 extras (`ok/extras`). En las
categorías bonus (`arrays`, `generators`, `interfaces`, `lambdas`, `macros`,
`oop`, `types`) la única falla registrada en el snapshot del 2026-06-14 es
`ok/macros/define_loop`.

El informe entregado por el equipo (`REPORT.md`, 2338 líneas, 13 961 palabras)
es notoriamente honesto: reconoce explícitamente las limitaciones (sección
21) y documenta el fallo de `define_loop` con su causa raíz (sección 20.10).
La verificación cruzada con el código confirma la mayor parte de sus
afirmaciones; los desajustes menores se detallan en la sección 11 de este
reporte.

---

## 2. Arquitectura del compilador

### 2.1 Workspace de quince crates

El `Cargo.toml` raíz (`Cargo.toml:1-30`) define un workspace con
`members = ["crates/*"]` y `resolver = "2"`. Los quince crates son:

| Crate              | Rol                                                | LOC (src)   |
|--------------------|----------------------------------------------------|-------------|
| `hulk-span`        | Spans y `SourceFile`                               | 169         |
| `hulk-diagnostics` | Bag de diagnósticos con `codespan-reporting`       | 337         |
| `hulk-tokens`      | Enum `Token`, tabla de keywords                    | ~150        |
| `hulk-ast`         | Nodos AST + visitors                               | ~1 200      |
| `hulk-lexer`       | Scanner con recuperación de errores               | ~625        |
| `hulk-parser`      | Pratt recursivo con sync tokens                    | ~2 130      |
| `hulk-semantic`    | Resolver, tabla de símbolos, validaciones          | ~1 700      |
| `hulk-types`       | Inferencia bottom-up + `TypeEnv`                   | ~1 250      |
| `hulk-hir`         | Wrapper que agrupa `program + symbols + types`     | 113         |
| `hulk-macros`      | Expansión de macros con higiene y patrones         | ~1 500      |
| `hulk-desugar`     | Transformaciones a un núcleo mínimo                | ~2 100      |
| `hulk-banner`      | Lowering a IR de tres direcciones                  | 1 096       |
| `hulk-codegen`     | Emisión de LLVM IR (`inkwell`) + enlazado          | ~3 300      |
| `hulk-driver`      | Orquestación del pipeline                          | 282         |
| `hulk-cli`         | Binarios `hulk` (contrato) y `hulkc` (dev)         | 141 + 98    |

Todos los crates verifican tener un `Cargo.toml` y código real; no hay
crates vacíos o stubs. El total de código de producción es de ~16 115 LOC
(sin contar tests, ejemplos, o el runtime en C).

### 2.2 Disciplina de capas y lints

El workspace declara lints estrictos en el `Cargo.toml` raíz
(`Cargo.toml:14-19`):

```toml
[workspace.lints.clippy]
all = { level = "warn", priority = -1 }
pedantic = { level = "warn", priority = -1 }
nursery = "deny"
unwrap_used = "deny"
expect_used = "deny"
```

Aplicar `unwrap_used = "deny"` y `expect_used = "deny"` en todo el workspace
es una decisión de disciplina que fuerza al equipo a propagar errores
mediante `Option`/`Result` o cerrar cada caso con un fallback explícito.

Las dependencias entre crates respetan una jerarquía por capas: `hulk-lexer`
depende de `hulk-tokens` y `hulk-diagnostics`; `hulk-parser` depende de
`hulk-ast`; `hulk-types` depende de `hulk-semantic`; `hulk-hir` agrupa
`hulk-ast + hulk-semantic + hulk-types`; los pases posteriores
(`hulk-macros`, `hulk-desugar`, `hulk-banner`, `hulk-codegen`) todos
dependen del HIR. `hulk-driver` es el que orquesta el pipeline completo.

### 2.3 Dos binarios: `hulk` y `hulkc`

El crate `hulk-cli` produce dos binarios distintos:

- `hulk` (`crates/hulk-cli/src/bin/hulk.rs:1-98`): interfaz de grading
  minimalista. Recibe `./hulk <file.hulk>`, produce `./output` en el
  directorio actual y reporta errores en formato `(line,col) TYPE: message`
  con exit codes 1 (léxico), 2 (sintáctico), 3 (semántico). La lógica
  `report_diagnostics` (`hulk.rs:64-79`) prioriza el tipo de error más
  fundamental cuando coexisten varios y traduce las coordenadas del
  diagnóstico restando el offset introducido por el prelude
  (`prelude_line_offset`, `compile.rs:27-31`).
- `hulkc` (`crates/hulk-cli/src/main.rs:1-141`): herramienta de desarrollo
  con subcomandos `compile`, `run`, `check` y flag `--emit` que permite
  volcar cualquier IR intermedio: `tokens`, `ast`, `hir`, `banner`,
  `llvm-ir`, `object`, `executable` (default).

Esta separación es correcta: el binario `hulk` implementa exactamente el
contrato del grading; `hulkc` es la interfaz rica para desarrollo. El
`Makefile` construye `hulk` con `cargo build --release --bin hulk` y lo
copia a la raíz del repositorio, como espera el CI.

---

## 3. Análisis léxico

El crate `hulk-lexer` (`crates/hulk-lexer/src/lib.rs`, 399 LOC) implementa
un scanner de descenso directo con recuperación de errores. Los submódulos
`tokens/{idents,numbers,strings,operators}.rs` particionan las reglas.

Aspectos verificados:

- **Recuperación de errores**: el lexer nunca aborta. Ante un carácter
  inesperado emite un diagnóstico y avanza al siguiente codepoint completo.
  El comentario en `lib.rs:121-128` documenta la técnica: avanzar por
  codepoint (no por byte) para no dejar el cursor a mitad de un UTF-8
  multibyte. Existe un test de regresión que ejercita `let 🦀 = 1 in 0;`
  y verifica que el lexer no paniquea (`lib.rs:361-383`).
- **Errores léxicos específicos**: identificadores con leading underscore
  (`_x`) se rechazan explícitamente (`lib.rs:69` → `lex_invalid_leading_underscore_identifier`).
  El símbolo `$` fuera del contexto de un placeholder de macro se reporta
  como carácter inesperado (`lib.rs:86-99`).
- **Operadores dobles**: `->`, `=>`, `==`, `!=`, `<=`, `>=`, `:=`, `@@`
  se distinguen mediante `double_or_single` y variantes especializadas
  del match principal (`lib.rs:102-119`).
- **Comentarios**: la ruta `consume_comment` avanza por codepoint para
  soportar UTF-8 en comentarios sin paniquear (`lib.rs:329-342`).
- **Alias léxicos**: `keyword_token` mapea `"function" | "define"` a
  `Token::Function` y `"protocol" | "interface"` a `Token::Protocol`
  (`crates/hulk-tokens/src/lib.rs:95, 106`). Esta decisión de tratar
  `define` como alias de `function` es crucial para entender el fallo de
  `define_loop` (véase sección 12).

---

## 4. Análisis sintáctico

El crate `hulk-parser` (`crates/hulk-parser/src/lib.rs`, 302 LOC + módulos
`complex.rs` 721, `expr.rs` 573, `decl/` ~360, `type_ann.rs` 102) implementa
un parser de Pratt con precedencias.

Aspectos verificados:

- **Recuperación multi-error**: `Parser::skip_to_sync` (`lib.rs:153-163`)
  usa un conjunto canónico de sync tokens: `Semicolon`, `RBrace`,
  `Function`, `Type`, `Protocol`, `Def`. Existe una guarda `ensure_progress`
  (`lib.rs:175-179`) que fuerza al menos un avance del cursor cuando la
  posición no cambió tras un intento de recuperación — la técnica clásica
  para evitar bucles infinitos en parsers con recuperación.
- **Modo generator**: el parser rastrea `gen_depth` para saber cuándo el
  operador `|` debe interpretarse como separador de generator
  (`[expr | x in it]`) y no como el operador booleano `Or`
  (`lib.rs:23-33`, `scan_is_generator` en `lib.rs:213-240`).
- **Distinguir función anónima vs declaración**: `peek_is_recovery_boundary`
  (`lib.rs:191-203`) explícitamente considera que `Token::Function`
  seguido de `LParen` es una lambda anónima (`function (`), no una
  declaración, y por tanto no es un límite de recuperación. Este detalle
  evita rechazar programas legítimos que empiezan con lambdas top-level.
- **Diagnósticos con contexto**: `expect` y `expect_ident` acumulan un
  `label` y un `note` que se propagan al `Diagnostic`
  (`lib.rs:107-141`), lo que produce mensajes de error con
  ubicación primaria + explicación secundaria.
- **Cubierta**: 168 LOC en `tests.rs` + `crates/hulk-parser/tests/error_recovery.rs`
  (374 LOC) prueban tanto la ruta feliz como los escenarios de recuperación.

---

## 5. Análisis semántico y sistema de tipos

### 5.1 Semántica (`hulk-semantic`)

El crate `hulk-semantic` está organizado en submódulos: `resolver/`
(subdividido en `mod.rs`, `builtins.rs`, `inheritance.rs`, `protocols.rs` y
`names/{decls, exprs, types}.rs`), `symbols.rs`, y `validation.rs`. Las
responsabilidades son claras:

- **Resolución de nombres**: `Resolver::resolve_program` construye una
  tabla de símbolos jerárquica y asocia cada `NodeId` de un
  `Ident`/`MethodCall`/`FieldAccess` con el `SymbolId` correspondiente.
- **Herencia y protocolos**: `resolver/inheritance.rs` valida la cadena de
  herencia y detecta ciclos; `resolver/protocols.rs` valida la conformidad
  estructural entre tipos y protocolos.
- **Validaciones adicionales**: `validation.rs` reporta redefiniciones,
  uso indebido de `self`/`base`, y otros checks estáticos.
- **Alcance de `base`**: el resolver es consciente del scope local — si
  existe una variable `base` en el scope actual, no la trata como super-
  referencia (documentado en `REPORT.md` sección 20.3).

### 5.2 Inferencia de tipos (`hulk-types`)

El corazón del sistema de tipos vive en `crates/hulk-types/src/inferer.rs`
(678 LOC). La estrategia real es una **inferencia bottom-up en una sola
pasada**, no una implementación de Hindley-Milner en su sentido
tradicional. Esta caracterización es admitida explícitamente por el propio
informe (`REPORT.md:664`) — pese a que el README del proyecto describe la
implementación como "sistema de constraints + unificación". El código no
contiene unificación, sustituciones de variables de tipo, ni
generalización de esquemas polimórficos; los términos `unify`, `constraint`
y `substitute` no aparecen en `crates/hulk-types/src/`.

Lo que sí hace el inferidor:

- Asigna un `TypeId` a cada `NodeId` de expresión y lo registra en
  `TypeEnv::expr_types` (`inferer.rs:227`).
- Los tipos primitivos se identifican como constantes `TypeId::NUMBER`
  (`= 1`), `STRING` (`= 2`), `BOOLEAN` (`= 3`) y `OBJECT` (`= 0`, tope de
  la jerarquía).
- Los operadores binarios devuelven un tipo fijo según su categoría
  (`inferer.rs:252-279`): aritmética → Number, concat/@@ → String,
  comparadores → Boolean, `&`/`|` → Boolean.
- `check_call_arity_and_types` (`inferer.rs:312-361`) valida aridad y
  tipos de argumentos contra las anotaciones declaradas del parámetro,
  emitiendo diagnósticos `SEMANTIC` cuando fallan. La relación
  `is_assignable` (`inferer.rs:366-374`) trata `Object` como comodín
  y por lo demás exige igualdad exacta de `TypeId` — no implementa
  covarianza real ni subtipado profundo.
- `check_function_return_type` (`inferer.rs:385-415`) verifica que el
  tipo inferido del cuerpo es asignable al tipo de retorno declarado.
- `register_function_params_by_name` y `register_method_params`
  (`inferer.rs:25-63`) pre-cargan los tipos de los parámetros desde las
  anotaciones declaradas antes de recorrer el cuerpo, evitando que los
  parámetros colapsen a `Object` durante la inferencia bottom-up.
- **Limitaciones deliberadas**: `infer_self`, `infer_base`,
  `infer_method_call` e `infer_field_access` devuelven `TypeId::OBJECT`
  (`inferer.rs:242-461`). El propio informe (sección 7.4 y 21.1) explica
  que esta pérdida de precisión no genera falsos positivos porque el
  codegen dispone de la información de tipos precisa a través de BANNER.

En síntesis: el sistema de tipos es funcional y correcto para el subconjunto
que la especificación HULK exige, pero **no es Hindley-Milner** y la
descripción "constraints + unificación" que aparece en el README es
inexacta. El informe corrige esta caracterización, lo cual es de agradecer.

---

## 6. HIR — representación intermedia tipada

El crate `hulk-hir` (`crates/hulk-hir/src/lib.rs`, 113 LOC) es un
**wrapper delgado** que agrupa tres artefactos ya producidos por fases
anteriores:

```rust
pub struct Hir {
    pub program: Program,    // AST
    pub symbols: Resolver,   // tabla de símbolos
    pub types:   TypeEnv,    // tipos por NodeId y SymbolId
}
```

`Hir::from_typed` es un mover trivial de los tres campos
(`lib.rs:33-40`). La API expuesta consiste en tres métodos de consulta
(`expr_type`, `symbol_type`, `resolved_symbol`) que permiten a los pases
posteriores (macros, desugar, BANNER) acceder a la información semántica
sin duplicarla.

El propio informe (`REPORT.md` sección 8.1) es explícito al respecto: el
HIR no es una transformación estructural del AST, sino una **estructura
de agrupación** que empaqueta los outputs del frontend. Esta caracterización
es correcta. En consecuencia, la descripción "HIR — typed intermediate
representation" que aparece en el README del proyecto es algo optimista
en cuanto a la ambición del HIR: no hay lowering a un lenguaje nuclear
distinto del AST, solo tipos adjuntos.

---

## 7. Expansión de macros

El crate `hulk-macros` implementa un expander real de macros
(`crates/hulk-macros/src/expander.rs`, 332 LOC) con higiene, patrones y
sustitución. Las macros se declaran con la keyword `def` (no `define`):

```
def name(params) => body
def name(params) { block }
```

### 7.1 Cuatro tipos de parámetro

`parse_macro_param` en `crates/hulk-parser/src/decl/macro_decl.rs:60-116`
distingue cuatro variantes por prefijo:

- Regular (sin prefijo): expresión substituida tal cual.
- `*body`: bloque `{ ... }` obligatorio (validado en `expander.rs:263-274`).
- `@symbol`: identificador que se substituye sin renombrado alfa.
- `$placeholder`: variable fresca que se registra en el resolver
  (`expander.rs:288-308`).

### 7.2 Higiene

`sanitize_locals` (`crates/hulk-macros/src/sanitize.rs`, 122 LOC)
implementa alpha-renombramiento hygiénico de todas las variables locales
introducidas por la macro. Cada `let`, `for`, `lambda`, y `VecGenerator`
en el cuerpo de la macro obtiene un nombre fresco de la forma
`__hulk_macro_<macro_name>_<expansion_id>_<original>`
(`sanitize.rs:116-121`).

El sanitizer mantiene una pila de scopes (`sanitize.rs:19`) para respetar
el shadowing correctamente y aplicar el renombrado solo dentro del scope
donde el binding es visible. Los tests en
`crates/hulk-macros/src/tests/sanitize.rs` y `placeholder.rs` ejercitan
casos donde un identificador exterior comparte nombre con una local de
la macro y verifican que no hay captura accidental.

### 7.3 Pattern matching

`crates/hulk-macros/src/pattern.rs` (337 LOC) implementa pattern matching
sobre subject expressions mediante intrinsics (`__hulk_case_lit`,
`__hulk_case_var`, `__hulk_case_binop`, `__hulk_case_binop_right_lit`,
`__hulk_default`) que el desugarer traduce a `match_pattern`. Las
patterns soportan:

- Literales (`same_literal` con tolerancia epsilon para números).
- Variables tipadas (`Number`, `String`, `Boolean`, `Object`).
- Binops con tipos en cada operando (`BinOp { op, left_ty, right_ty }`).
- Binops con literal a la derecha (`BinOpRightLiteral`).
- Caso default.

`simplify_algebraic` (`pattern.rs:313-315`) aplica identidades algebraicas
sobre las substituciones (x+0 → x, x*1 → x, x*0 → 0, etc.) como
simplificación local a nivel de macros.

### 7.4 Pipeline de expansión

`expand_macros` (`expander.rs:25-65`) corre **después de la inferencia de
tipos** y **antes del desugaring**:

```rust
let hir = build_hir(program, &mut bag)?;        // lex+parse+resolve+infer
let hir = expand_macros(hir, &mut bag);         // macros aquí
if bag.has_errors() { return Err(...); }
Ok(desugar(hir, bag))
```

`MacroExpander::expand_expr` visita cada expresión, evalúa pattern-matches
primero, recurre a hijos, y finalmente reescribe las `Call` cuyo callee
sea una macro registrada mediante `expand_macro_call`
(`expander.rs:203-258`). Cada expansión incrementa `expansion_counter`
para producir nombres frescos únicos por sitio de llamada.

---

## 8. Desugar + BANNER IR

### 8.1 Desugaring (`hulk-desugar`)

El crate `hulk-desugar` (`crates/hulk-desugar/src/lib.rs`, 411 LOC + módulos
`transforms/{array_gen, for_loop, lambda, string_concat, vec_generator}.rs`)
transforma construcciones de alto nivel en un núcleo más pequeño:

- `for (x in it) body` → `let it_var = <iter> in while (it_var.next()) { let x = it_var.current() in body }`. La estrategia se elige según el tipo del iterable (Iterable directo vs Enumerable con `.iter()`), en `for_loop.rs`.
- `a @@ b` → `a @ " " @ b` (`string_concat.rs`).
- Lambdas con captura → un tipo sintético con campo de captura + método
  `invoke(...)`. La sección 10.3 del informe describe la técnica, y la
  transformación reside en `transforms/lambda.rs` (709 LOC — el módulo
  más largo del desugarer).
- `[expr | x in it]` (vector generators) → un `let __vec = __vec_new() in { for (x in it) __vec_push(__vec, expr); __vec }` (`vec_generator.rs`).
- `new T[N]` → `let arr = __arr_new(N) in ...` (`array_gen.rs`).

Los tests en `crates/hulk-desugar/tests/equivalence.rs` (394 LOC) y
`combined.rs` (434 LOC) verifican que los programas conservan semántica
tras el desugaring.

### 8.2 BANNER IR (`hulk-banner`)

`crates/hulk-banner/src/ir.rs` (156 LOC) define el IR de tres direcciones:

- `TempId(u32)`: handle opaco para temporales.
- `Value`: temporal, constantes primitivas, o global.
- `Instr`: 20 variantes que incluyen `Copy`, `BinOp`, `UnOp`, `Call`,
  `MethodCall`, `StaticCall`, `New`, `GetField`, `SetField`, `GetIndex`,
  `SetIndex`, `Label`, `Jump`, `JumpIf`, `Return`, `ShadowPush`,
  `ShadowPop`, `Alloc` (reservado, no emitido por el lowerer).
- `BannerFunction { name, params, param_names, param_runtime_hints, body }`.
- `TypeDescriptor { name, parent, fields, pointer_map, field_kinds, methods }`.
- `FieldKind { Number, Boolean, Reference }` para que el codegen pueda
  diferenciar `f64`, `i1` y `ptr` en las alocaciones.
- `BannerProgram { types, functions, main }`.

`crates/hulk-banner/src/lowerer.rs` (1 096 LOC) es el módulo que traduce
HIR → BANNER. Las decisiones destacables:

- **Manejo dual de locales**: `locals: HashMap<SymbolId, TempId>` para
  bindings que el resolver conoce, `locals_by_name: HashMap<String, TempId>`
  como fallback para variables sintéticas introducidas por el desugarer
  (por ejemplo, los iteradores de `for`).
- **Contabilidad de shadow stack**: `shadow_count: usize` se guarda y
  restaura alrededor de cada `Let` para que las anidaciones emitan solo
  las `ShadowPop` que les corresponden.
- **`param_runtime_hint`**: los parámetros anotados con tipos de usuario
  (por ejemplo `other: Vector`) propagan el nombre del tipo al
  `temp_type_names` del codegen, para que los accesos a campos resuelvan
  correctamente los offsets del struct (documentado como corrección 20.5
  en `REPORT.md`).

El módulo tiene `crates/hulk-banner/src/print.rs` para pretty-printing
(útil para `hulkc --emit banner`), y una suite de tests que incluye
`shadow_stack.rs` — el archivo referenciado por el informe (sección 14.3)
para probar el manejo de raíces según el tipo del binding.

---

## 9. Backend / Codegen LLVM

El crate `hulk-codegen` (~3 300 LOC entre `codegen.rs`, `emit.rs`,
`emit_call.rs`, `emit_mem.rs`, `emit_ops.rs`, `rt.rs`, `layout.rs`,
`link.rs`, `pipeline.rs`, `error.rs`, y `lib.rs`) emplea `inkwell 0.4` con
la feature `llvm17-0` para emitir LLVM IR.

Estructura verificada:

- `Codegen<'ctx>` (`codegen.rs:65-100+`) mantiene el contexto LLVM, el
  módulo, el builder, layout de vtables por tipo, declaraciones de
  runtime, mapas de temporales a slots y kinds, y ciertas tablas
  auxiliares. `TempKind` (`codegen.rs:24-33`) distingue `F64`, `I1` y
  `Ptr` para que cada alloca use el tipo LLVM correcto.
- `predeclare_all` inicializa las declaraciones de tipos, vtables y
  funciones (tanto de usuario como de runtime); `emit_program` emite los
  cuerpos.
- Enlazado: `crates/hulk-codegen/src/link.rs` compila el módulo LLVM a un
  archivo objeto vía `TargetMachine::write_to_file` (`link.rs:38-40`) y
  luego invoca un linker externo (`clang`, `clang-17`, `cc`, o `gcc`, en
  ese orden — `link.rs:99-106`) para producir el ejecutable, enlazando
  `libhulkruntime.a` y `libm`.
- Runtime compilado como archivo `.a` en tiempo de construcción:
  `crates/hulk-codegen/build.rs` compila `gc.c`, `strings.c`, `builtins.c`
  con `gcc -O2 -Wall -Werror` y produce `libhulkruntime.a` en el `OUT_DIR`
  de cargo (`build.rs:11-51`). Este archivo se enlaza estáticamente en el
  ejecutable final.

El codegen soporta despacho virtual mediante vtables (visible en la
estructura `TypeDescriptor.methods` de BANNER y en los campos
`vtable_globals` de `Codegen`), llamadas a métodos y a base, downcasts
con `__hulk_as`, y el completo conjunto de operadores. La ruta de
igualdad (`emit_ops.rs`) despacha según el `TempKind` del primer operando:
`F64` → `fcmp oeq/une`, `I1` → `icmp eq/ne`, `Ptr` → llamada a
`__hulk_str_eq` del runtime (documentado como corrección 20.4).

Las suites `crates/hulk-codegen/tests/integration.rs` (1 055 LOC) y
`comprehensive.rs` (1 021 LOC) ejercitan escenarios end-to-end del codegen
compilando programas HULK y verificando salida.

---

## 10. Runtime en C con recolector de basura

El directorio `runtime/` contiene la biblioteca de soporte que se enlaza
al ejecutable final:

- `gc.c` (100 LOC) — recolector de basura.
- `gc.h` (58 LOC) — tipos `TypeTag`, `ObjHeader`, macros `HULK_PAYLOAD`/`HULK_HEADER`.
- `builtins.c` (218 LOC) — implementaciones de `hulk_print`,
  `hulk_range_new`, `__vec_*`, `__arr_new`, `__objarr_*`, `__hulk_is`,
  `__hulk_as`, y funciones matemáticas.
- `strings.c` (78 LOC) — `hulk_string_new`, `hulk_string_concat`,
  `__str_size`, `__str_char_at`, `__str_substring`, `__hulk_str_eq`.
- `builtins.h`, `strings.h` — headers correspondientes.
- `test_gc.c`, `test_strings.c` — tests C independientes.

### 10.1 Recolector mark-and-sweep preciso

El GC implementado es un **recolector mark-and-sweep preciso con shadow
stack para las raíces**, no una integración con Boehm-Weiser (el README
en línea 121 dice erróneamente "Runtime en C con GC (Boehm)" — es una
imprecisión de documentación; el código en `runtime/gc.c` es
implementación propia).

Estructura verificada (`runtime/gc.h:1-58`):

```c
typedef struct TypeTag {
    const char*     name;
    size_t          num_pointers;
    size_t*         pointer_offsets;
    struct TypeTag* parent;
} TypeTag;

typedef struct ObjHeader {
    TypeTag*          tag;
    size_t            size;
    int               mark;
    struct ObjHeader* next;
} ObjHeader;
```

Cada allocación pre-pende un `ObjHeader` que incluye un puntero al
`TypeTag`, el tamaño total, el bit de marca, y un `next` para enlazar
todas las allocaciones en una lista intrusiva. El `TypeTag` describe la
forma del objeto: nombre, número de campos que son punteros, offsets de
esos campos, y puntero al padre en la cadena de herencia (usado por
`__hulk_is` para downcasts).

### 10.2 Algoritmo (`runtime/gc.c:15-57`)

- **Marca**: `mark(void* payload)` recorre recursivamente el objeto,
  marca el bit `hdr->mark`, y para cada offset de puntero declarado en
  el `TypeTag`, deriva el hijo y lo marca. Corta en `NULL` o en objetos
  ya marcados, manejando ciclos correctamente (comentario en
  `gc.c:15-17` lo explica).
- **Sweep**: recorre la lista global `__hulk_alloc_list`, elimina los
  objetos no marcados llamando a `free`, decrementa `__hulk_alloc_bytes`,
  y limpia el bit de marca en los sobrevivientes.
- **Ajuste dinámico del umbral**: tras cada colección,
  `__hulk_gc_threshold` se recalcula como `2 * live_bytes`
  (`gc.c:52-56`), con un mínimo de 1 MiB. Esto reduce la frecuencia de
  colecciones a medida que el working set crece.

### 10.3 Shadow stack

Las raíces vivas se mantienen explícitamente en un array plano de tamaño
fijo (`gc.h:41-42`, `HULK_SHADOW_STACK_CAPACITY = 4096`). El codegen
emite `ShadowPush`/`ShadowPop` en las instrucciones BANNER que introducen
o descartan variables de tipo referencia. En runtime, `hulk_shadow_push`
y `hulk_shadow_pop` (`gc.c:86-100`) validan overflow/underflow y abortan
con mensaje de error controlado si se violan.

El adjetivo "preciso" aplica: solo los slots explícitamente empujados a
la shadow stack son visitados por la fase de marcado, y solo los offsets
declarados en el `TypeTag` son seguidos como punteros. No hay escaneo
conservativo de la pila C.

### 10.4 Trigger de colección

`hulk_alloc` (`gc.c:59-84`) comprueba antes de cada allocación si
`__hulk_alloc_bytes + total > __hulk_gc_threshold`, en cuyo caso invoca
`hulk_gc()`. Si tras la colección aún no cabe, aborta con
`"hulk: out of memory after GC"`. La política es simple pero funcional
para programas HULK típicos.

### 10.5 Tests del GC

`runtime/test_gc.c` (86 LOC) ejercita el GC con tests C directos. Los
programas HULK del directorio `stress-test/gc/` ejercitan el sistema
end-to-end (crear muchos objetos, forzar colecciones, verificar que las
raíces sobreviven).

---

## 11. Discrepancias entre `REPORT.md` y código

La verificación cruzada arroja que el `REPORT.md` es en gran medida
preciso; los desajustes son menores y en su mayoría atribuibles a
descripciones del README (no del informe técnico principal). Los
principales:

1. **Sistema de tipos**: el `README.md:119` describe el sistema como
   "Inferencia de tipos (sistema de constraints + unificación)"; el
   código no implementa unificación ni constraints. El
   `REPORT.md:664` corrige explícitamente esto ("**No es
   Hindley-Milner**"), de modo que la discrepancia queda internamente
   documentada.

2. **GC Boehm**: `README.md:121` menciona "GC (Boehm)"; el código en
   `runtime/gc.c` es una implementación propia de mark-and-sweep
   preciso con shadow stack. El `REPORT.md` sección 14 describe
   correctamente el algoritmo real; la imprecisión está solo en el
   README.

3. **HIR**: el `README.md:31` describe `hulk-hir` como "High-level IR
   con tipos anotados". En rigor, `hulk-hir` es un wrapper delgado que
   agrupa `Program + Resolver + TypeEnv` sin transformar la estructura.
   El `REPORT.md:773` lo describe como "estructura de unificación"
   (donde "unificación" aquí es en el sentido de agrupación,
   no de unificación de variables de tipo). No hay lowering distinto
   del AST.

4. **`define` como macro**: el `README.md:104` dice
   "Declaración: `def macro(*args: Type): Type => body`", sugiriendo
   que `define` no es una keyword de macro. En efecto el código trata
   `define` como alias léxico de `function` (véase sección 12); el
   informe (sección 20.7) documenta explícitamente esta elección. Los
   tests bonus del grading usan `define` como si fuera una macro, y de
   ahí surge el único fallo.

5. **Cifras de tests**: el `README.md:233` menciona "los 750+ tests"; la
   suite unitaria confirma este orden de magnitud entre los tests de
   cada crate (`crates/hulk-ast/tests/coverage/*`, `crates/hulk-desugar/tests/*`,
   etcétera). No pude ejecutar `cargo test` en esta evaluación para dar
   el conteo exacto, pero la cifra parece razonable dada la extensión
   del código de tests (~17 500 LOC).

---

## 12. La única falla: `ok/macros/define_loop`

### 12.1 El caso de prueba

`tests/tests/hulk/ok/macros/define_loop.hulk`:

```hulk
define repeat(times: Number, body: Number): Number {
    let i: Number = times in
        while (i > 0) {
            i := i - 1;
            body;
        };
}

let count = 0 in {
    repeat(5, count := count + 1);
    if (count == 5) print("ok") else print("fail");
};
```

Salida esperada: `ok`.

### 12.2 Causa raíz

El fallo tiene una causa clara y bien documentada por el equipo en la
sección 20.10 del informe. El lexer trata `define` como alias léxico
de `function` (`crates/hulk-tokens/src/lib.rs:95`). En consecuencia,
`define repeat(times: Number, body: Number): Number { ... }` se parsea
como una **declaración de función normal**, no como una macro.

Las funciones en HULK usan **semántica de call-by-value**: el argumento
`count := count + 1` se evalúa **una vez**, en el momento de la llamada,
produciendo un `Number` (el valor 1, con efecto secundario sobre `count`).
Dentro del cuerpo de la función, el parámetro `body` es un `Number` con
valor 1; la expresión `body;` en el bucle `while` es una evaluación de
un número, sin efecto lateral. Como resultado, `count` termina valiendo
1, no 5, y la comparación `count == 5` es falsa. El programa imprime
`fail` en lugar de `ok`.

### 12.3 Qué se necesitaría para arreglarlo

Para que `define_loop` funcione se requiere una de dos vías:

- **Expansión real de `define` como macro** (call-by-name / substitución
  textual). Requeriría añadir un nuevo AST y ruta de parseo que produzca
  un `MacroDecl` en lugar de una `FunctionDecl`, y garantizar que la
  expansión de macros ocurra sobre las llamadas a `define`. La
  infraestructura de expansión existe (`crates/hulk-macros/`) y ya
  maneja parámetros de tipo `Body` con el prefijo `*` según la
  documentación. Sería un trabajo de integración, no de invención
  desde cero.
- **Argumentos por thunk** (call-by-need): envolver cada argumento en
  una lambda cero-aria y desreferenciarlo dentro del cuerpo. Menos
  natural para el lenguaje y no coincide con la semántica esperada.

El equipo lo documenta como "fuera del alcance de esta iteración"
(`REPORT.md:2199-2201`) — decisión razonable dado que el resto del
grupo `ok/macros/` (7 tests) sí pasa con la interpretación
call-by-value, porque en esos casos la evaluación única del argumento
produce el resultado correcto.

### 12.4 Nota adicional

El REPORT.md línea 2094 y el código confirman que el equipo intentó una
solución rápida (aliasar `define` a `function`) que resuelve 7 de 8
casos del grupo macros, y elige documentar el 8º como limitación
conocida en lugar de emprender la implementación completa de una macro
real con expansión. Es una decisión de ingeniería defendible, y aumenta
la nota bruta del proyecto de 70/71 requeridos + 9/10 extras a 71/71
+ 10/10 extras + una única falla en la categoría bonus más difícil.

---

## 13. Features implementadas — verificación

| Feature      | Estado según CI | Verificación en código                                         |
|--------------|-----------------|----------------------------------------------------------------|
| minimal      | 20/20           | Lexer, parser, driver, codegen completos                       |
| types        | 10/10           | Tipos, herencia, `is`, `as`, `base`; `vtable_globals` presente |
| oop          | 10/10           | Métodos virtuales, downcasts, atributos, dispatch dinámico     |
| errores      | 31/31           | Recuperación en lexer y parser + validaciones semánticas       |
| extras       | 10/10           | `ok/extras/` no obligatorio pero implementado                  |
| arrays       | passing         | `__arr_new`, `__objarr_new`, `ArrayGen`, `ArrayNew`            |
| generators   | passing         | `VecGenerator` con hygiene en el sanitize                      |
| interfaces   | passing         | `protocol` con alias léxico `interface`                        |
| lambdas      | passing         | `transforms/lambda.rs` (709 LOC) — tipo sintético + `invoke`   |
| macros       | 7/8             | `define_loop` falla; los otros 7 (`simple_define`, `hygiene`, `block`, `chain`, `conditional`, `nested`, `recursive_expand`) pasan |
| oop bonus    | passing         | Herencia compleja, polimorfismo, downcasts                     |
| types bonus  | passing         | Casos avanzados de sistema de tipos                            |

Todas las features marcadas en el issue #24 tienen soporte real en el
código; ninguna es puramente aspiracional.

---

## 14. Fortalezas y aspectos destacados

1. **Ambición arquitectural**: 15 crates con separación clara de
   responsabilidades es infraestructura de proyecto industrial, no de
   proyecto de curso. Cada crate expone una API mínima y sus tests
   corren aislados.

2. **Runtime propio en C con GC preciso**: implementar un mark-and-sweep
   con shadow stack, `TypeTag` con pointer offsets y descubrimiento
   dinámico del working set (`GC_GROWTH_FACTOR`) es trabajo real. El
   código en `runtime/gc.c` está bien comentado y respeta las
   convenciones de precisión (no escaneo conservativo).

3. **BANNER como IR intermedio explícito**: separar el lowering a un
   3-address IR de la emisión LLVM reduce el acoplamiento y facilita
   futuras optimizaciones locales. `crates/hulk-banner/src/lowerer.rs`
   (1 096 LOC) es rigurosa en el manejo de shadow stack y locales.

4. **Higiene de macros implementada**: `sanitize_locals` implementa
   alpha-renombramiento real con manejo de scopes. Los tests
   ejercitan escenarios de shadowing y verifican ausencia de captura
   accidental.

5. **Dos binarios contract + dev**: la separación entre `hulk`
   (interfaz de grading) y `hulkc` (dev con `--emit`) refleja
   comprensión del contrato de evaluación y de la ergonomía de
   desarrollo.

6. **Lints estrictos**: `unwrap_used = deny` y `expect_used = deny` en
   todo el workspace es disciplina de código que fuerza a propagar
   errores correctamente.

7. **Recuperación de errores**: el lexer y el parser nunca abortan;
   producen múltiples diagnósticos en una sola pasada. Los sync tokens
   canónicos y `ensure_progress` son técnicas estándar bien
   aplicadas.

8. **REPORT.md honesto y detallado**: 2 338 líneas, 13 961 palabras,
   documenta tanto las decisiones de diseño como las correcciones
   iterativas (secciones 20.1–20.10) y las limitaciones conocidas
   (sección 21). El nivel de honestidad sobre lo que no es
   Hindley-Milner (línea 664) es de agradecer.

9. **Suite de tests extensa**: ~17 500 LOC de tests distribuidos en
   `crates/*/tests/`, `crates/*/src/tests.rs`, y un directorio
   `stress-test/` con programas de tortura para el GC.

---

## 15. Aspectos menores a corregir

Ninguno afecta la corrección funcional del compilador, pero merece
mención para futuras iteraciones:

- **Consistencia entre README y REPORT.md**: las tres discrepancias
  mencionadas en la sección 11 (constraints/unificación, Boehm, HIR
  como transformación) están todas en el README. Alinearlas al informe
  técnico eliminaría cualquier ambigüedad.

- **Implementación real de macros con `define`**: aunque el equipo lo
  documenta como fuera de alcance, la infraestructura de expansión
  existe. Añadir una nueva ruta de parseo para `define` que produzca un
  `MacroDecl` en lugar de un `FunctionDecl` cerraría el único fallo del
  grading.

- **Sección `21.2` (clausuras con captura desde función global)**:
  documentada como limitación por el propio equipo. El ejemplo
  `function f(n) => (x) => x + n;` produce error `param not in
  param_temps`; la mitigación propuesta (usar un tipo con método
  `apply`) es válida pero requeriría reformular los tests de lambdas
  que dependan del patrón.

---

## 16. Conclusión

La entrega de Dayan Cabrera Corvo es, con alta probabilidad, la más
ambiciosa y completa del cohorte 2026 sobre la que tengo evidencia. El
compilador implementa **todas** las categorías obligatorias con 100%
de tests, incluye 10/10 extras, y aprueba las siete categorías bonus
menos un único caso (`define_loop`) cuya causa raíz está documentada
y es una consecuencia del atajo pragmático de tratar `define` como
sinónimo de `function`.

La calidad del código va más allá de "pasa los tests":

- Un workspace de 15 crates con dependencias limpias por capas.
- Un runtime en C con recolector de basura mark-and-sweep preciso y
  shadow stack para las raíces (implementación propia, no Boehm).
- Un IR intermedio explícito (BANNER) que separa el lowering del
  backend LLVM.
- Higiene real de macros con alpha-renombramiento por scope.
- Dos binarios que respetan tanto el contrato de grading como la
  ergonomía de desarrollo.
- Lints estrictos aplicados a todo el workspace.
- Un informe técnico de 2 338 líneas honesto sobre lo que se
  implementó y lo que no.

Las tres discrepancias entre el `README.md` y el código son menores
(y todas están documentadas correctamente en el `REPORT.md`); la
única falla real es un caso conocido y explicado.

Este proyecto merece ser reconocido como una entrega ejemplar del
curso de Compiladores. La combinación de ambición técnica,
disciplina de ingeniería, y honestidad en la documentación es rara y
señala trabajo significativo sostenido durante todo el semestre.
