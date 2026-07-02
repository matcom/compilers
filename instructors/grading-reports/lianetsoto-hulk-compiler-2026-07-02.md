---
student: Aixa Bazán Rodríguez, Amanda Medina Solis, Lianet Soto Aguirre
issue: 46
repo: LianetSoto/Hulk_Compiler
branch: main
date: 2026-07-02
---

# Evaluación técnica — Compilador HULK del equipo LianetSoto

## 1. Descripción arquitectónica

### 1.1 Panorama general

El compilador está escrito en **Rust 2024** y produce código nativo mediante **LLVM 17** a través del binding seguro **Inkwell 0.4** (`Cargo.toml:8-11`). El parser se genera con **LALRPOP 0.23.0** (`Cargo.toml:14-15`). El proyecto se organiza como una cadena unidireccional lexer → parser → semántica → transformación → codegen → linker, siguiendo la separación clásica de un compilador de un solo pase de análisis por etapa.

### 1.2 Cadena de compilación

El punto de entrada `src/main.rs` distingue dos modos en tiempo de compilación mediante la feature `dev`. En modo `dev` (`src/main.rs:5-56`) se activan trazas verbosas por etapa, y en modo CI (`src/main.rs:58-115`) el binario acepta exactamente un archivo, emite errores con el formato `(línea,columna) TIPO: mensaje` y traduce a códigos de salida `1` (LexerError), `2` (ParserError) y `3` (semántica u otros). Este contrato es el que consume el corredor de tests del curso.

Toda la coreografía del pipeline vive en `src/compiler.rs`:

1. `build_lexer()` construye los autómatas Thompson-DFA para las palabras clave (`src/compiler.rs:33`).
2. `tokenize` produce la lista de tokens con posiciones (`src/compiler.rs:37`).
3. `parse_program` invoca al parser LALRPOP (`src/compiler.rs:53`).
4. `TypeChecker::check` corre el análisis semántico y devuelve el AST anotado (`src/compiler.rs:66`).
5. `MonomorphizationPass::run` clona funciones genéricas por instancias concretas (`src/compiler.rs:74`).
6. `LlvmCodeGen` recorre el AST monomorfizado y emite IR (`src/compiler.rs:84`).
7. Se escribe `output.ll` y se invoca `clang-17` como enlazador (`src/compiler.rs:99-114`).

### 1.3 Módulos y responsabilidades

- `src/lexer/` y `src/gen_lex/` (lexer analógico con NFA/DFA + escáner escrito a mano).
- `src/grammar.lalrpop` + `src/parser/parser.rs` (gramática y wrappers de parseo).
- `src/ast/` (definición de nodos + trait `Visitor`).
- `src/semantic/` (inferencia HM-lite, `TypeChecker`, resolución de flatten de tipos).
- `src/transform/monomorphization_pass.rs` (especialización de funciones genéricas).
- `src/codegen/` (LLVM IR, VTables, runtime, RTTI).
- `src/error/error.rs` (variantes de error unificadas).

Los módulos son físicamente distintos y no hay ciclos de importación cruzados: `semantic` importa de `ast`, `codegen` importa de `ast` + `semantic`, y `transform` opera sobre `ast` + `semantic`. La estructura es coherente y facilita seguir el flujo lineal del compilador.

### 1.4 Modelo de datos del AST

El AST en `src/ast/expr.rs` (`Expr`) tiene 22 variantes: `Number`, `String`, `Bool`, `Const`, `Variable`, `SelfExpr`, `Base`, `BinaryOp`, `UnaryOp`, `Call`, `Let`, `If`, `While`, `For`, `Block`, `DestructiveAssign`, `AttributeAccess`, `MethodCall`, `New`, `Is`, `As`. Cada nodo trae `Span` y un campo opcional `ty: Option<HulkType>` para anotaciones de tipo, patrón que permite acumular información durante la fase semántica sin refactor.

`src/ast/type_def.rs` modela declaraciones OO: `TypeDef`, `Attribute`, `Method`, `ProtocolDef`, `ProtocolMethod`, `Parent`. Esta división entre expresiones y declaraciones es estándar y bien hecha.

**Ausencias notables en el AST**: no existen `NewArray`, `IndexAccess`, `Lambda` ni `Define/Macro`. Esto se correlaciona directamente con las fallas de CI que se discuten más abajo.

### 1.5 Manejo de errores

`src/error/error.rs` define `CompilerError` con variantes `LexerError`, `ParserError`, `TypeError`, `CodegenError`, `IoError`, `MonomorphizationError`, cada una portando `Span`. El método `report_std_error` produce la línea `(l,c) TYPE: message` que espera el runner de CI.

### 1.6 Runtime y linking

El backend produce `output.ll`, ejecuta `clang-17 -o output output.ll -lm`, y opcionalmente `-fuse-ld=lld` si LLD está disponible. No hay biblioteca de runtime propia en Rust; todas las utilidades de I/O y aritmética (`printf`, `sin`, `cos`, `sqrt`, `rand`, `malloc`) se declaran directamente en el IR. `hulk_instanceof` sí es una función completamente generada por el propio codegen como cuerpo LLVM.

### 1.7 Uso de LLVM

`LlvmCodeGen` (`src/codegen/llvm.rs`) mantiene `context`, `module`, `builder`, `scopes`, `method_functions`, `type_structs`, `flattened_types`, `vtables` y `vtable_types`. Correspondencia de tipos HULK→LLVM: `Number` → `f64`, `Boolean` → `i1`, `String` → `i8*`, `Class(_)` → puntero a `%TypeName` con VTable como primer campo.

### 1.8 Estrategia de despacho

Despacho virtual mediante VTables. El primer campo de cada instancia (campo 0) es un puntero opaco al VTable de su clase concreta. El VTable es un `struct { i32 type_id; ptr parent_vtable; [N x ptr] methods }` global constante. El chequeo runtime `is` recorre la cadena de padres comparando `type_id`.

---

## 2. Lexer

### 2.1 Diseño

El lexer es **híbrido**: usa autómatas construidos por **algoritmo de Thompson** para las palabras reservadas y un escáner escrito a mano para números, identificadores, strings, operadores y whitespace. La construcción vive en `src/gen_lex/thompson.rs` y `src/gen_lex/dfa.rs`; el driver en `src/gen_lex/lexer.rs`.

### 2.2 Cobertura de tokens

`src/lexer/token.rs` define 62 variantes del `enum Token`: palabras clave (`print`, `function`, `let`, `in`, `if`, `else`, `elif`, `while`, `for`, `true`, `false`, `type`, `inherits`, `new`, `protocol`, `extends`, `is`, `as`), constantes (`PI`, `E`), built-ins matemáticos, tipos primitivos, operadores (`+`, `-`, `*`, `/`, `^`, `%`, `.`, `,`, `:`, `;`, `@`, `@@`, `=`, `:=`, `=>`, `==`, `!=`, `<`, `>`, `<=`, `>=`, `&`, `|`, `!`, `->`), y literales `Number(f64)`, `Str(String)`, `Identifier(String)`.

**Notablemente no hay tokens de corchetes** `[` `]`. Esto imposibilita la sintaxis de arrays desde el nivel léxico.

### 2.3 Comentarios y escapes

En `src/gen_lex/lexer.rs:133` el lexer reconoce comentarios de línea con `//`. Escapes en strings: `\n`, `\t`, `\"`, `\\`. No hay comentarios de bloque `/* ... */`.

---

## 3. Parser

### 3.1 Estrategia

`src/grammar.lalrpop` (803 líneas) define una gramática **LALR(1)** procesada por LALRPOP en `build.rs`. El wrapper `src/parser/parser.rs` invoca el parser generado y traduce errores de LALRPOP a `CompilerError::ParserError`.

### 3.2 Precedencia

Nueve niveles de precedencia (menor a mayor): `LogicalOrExpr` (`|`), `LogicalAndExpr` (`&`), `ComparisonExpr`, `AddSubExpr` (`+`, `-`, `@`, `@@`), `MulDivExpr` (`*`, `/`, `%`), `PowerExpr` (`^` asoc. derecha), `UnaryExpr`, `PostfixExpr` (llamadas, `.`, `is`, `as`), `AtomicExpr`.

### 3.3 Desugaring

- `elif` se desugariza en el propio nivel de gramática construyendo un `If` anidado en la rama `else` (`grammar.lalrpop:465-486`). No existe un nodo `Elif` en el AST.
- La azúcar `T*` para `Iterable(T)` se aplica en la regla `Type: HulkType` (`grammar.lalrpop:89-92`).
- `for (x in iter) body` **no se desugariza en el parser** sino que se difiere hasta codegen.

### 3.4 Ambigüedad `is`/`as` con `*`

Para evitar que `is Number*` sea parseado como `(is Number) * ...`, `is` y `as` no reciben `Type` sino `TypeBase`, un no terminal que excluye la azúcar `*`.

### 3.5 Cobertura

Cubre declaraciones de tipo con `inherits`, atributos y métodos, protocolos con `extends`, funciones globales con parámetros tipados, `let ... in ...` con múltiples bindings, `if/elif/else`, `while`, `for`, `new`, `is`, `as`, bloques.

No cubre: sintaxis de arrays `[a, b, c]` ni indexación `x[i]`, lambdas, macros.

---

## 4. Análisis semántico

### 4.1 Modelo de tipos

`src/semantic/types.rs` define el `enum HulkType`: `Number`, `String`, `Boolean`, `Object`, `UserDefined(String)`, `Error`, `Var(usize)`, `Class(String)`, `Protocol(String)`, `GenericPlaceholder`, `Iterable(Box<HulkType>)`.

La coexistencia de `UserDefined`, `Class` y `Protocol` sugiere una migración incompleta.

### 4.2 Inferencia y unificación

`src/semantic/inference.rs` define `Unifier` con `subs`, `next_var` y `constraints`. Constraints diferidas de dos variantes: `StringOrNumber` (para `@`/`@@`) y `ConformsToProtocol(String)`.

`unify` maneja: `Var ~ Var` con occurs-check, `Var ~ T` (bind + propagación), igualdad estructural de primitivos, igualdad nominal de clases y protocolos, `Iterable(A) ~ Iterable(B)` recursiva.

El diseño es **HM-lite**: no hay let-polimorfismo generalizado. El polimorfismo aparece en funciones globales genéricas y se resuelve por **monomorfización** aguas abajo.

### 4.3 TypeChecker

`src/semantic/type_checker.rs` (2857 líneas) ejecuta cinco fases: `visit_program`, `resolve_ast`, `flatten_all_types`, `resolve_flattened_types`, `verify_no_type_vars`. `errors: Vec<CompilerError>` permite acumular varios errores por corrida.

### 4.4 Registros built-in

- Protocolo `Iterable` con método `next(): Boolean` y `current(): Object`.
- Protocolo `Enumerable extends Iterable` que expone `iter()`.
- Tipo interno `_Range` usado por la desugarización de `range(a, b)`.

### 4.5 Herencia y conformancia

Se chequea que el padre exista, se prohíbe heredar de primitivos, se detectan tipos duplicados.

**No se detectan ciclos de herencia.** Una búsqueda por `detect_cycle`, `visited`, `cycle` no arroja código para esa verificación. Un programa con `type A inherits B; type B inherits A;` puede colapsar la fase de `flatten_all_types`.

`lowest_common_ancestor` computa el LCA para inferir el tipo del `if/else`. `conforms_to` maneja subtipado nominal por herencia, conformancia estructural a protocolos, y `Iterable(T)` como caso especial.

### 4.6 Protocolos estructurales

Los protocolos son **estructurales**: `T` conforma a `P` si expone todos los métodos declarados en `P`. No se requiere `implements` explícito. El test `tests/ok/protocols.hulk` demuestra este mecanismo.

### 4.7 Monomorfización

`src/transform/monomorphization_pass.rs` clona cada función genérica una vez por combinación única de tipos concretos. El nombre mangleado usa `$` como separador.

**Bug detectado**: en `monomorphization_pass.rs:215-217` el brazo del match para `Expr::For` está vacío. Si un `for` está dentro de una función genérica y su iterable o cuerpo contiene tipos variables, la sustitución no se propaga.

**Bug adicional**: `type_to_string` (`monomorphization_pass.rs:84-97`) hace `todo!()` para `HulkType::GenericPlaceholder` y `HulkType::Iterable(_)`.

---

## 5. Generación de código

### 5.1 Layout de memoria

`src/codegen/types_codegen.rs`, `build_struct_type_from_flat` construye el struct LLVM: campo 0 `i8*` opaco (VTable), campos 1..N atributos aplanados (padre primero). Compatibilidad binaria en upcasts garantizada.

### 5.2 VTables

`generate_vtable` produce `struct { i32 type_id; ptr parent_vtable; [N x ptr] methods }` como global constante por clase.

### 5.3 Instanciación

`visit_new` (`src/codegen/llvm_visitor.rs`): `malloc(sizeof(TypeStruct))`, cast, store del VTable global, asignación de argumentos a campos. Sin GC.

### 5.4 Despacho virtual

`call_virtual_method`: Load del VTable desde campo 0, GEP al slot `[method_index]`, indirect call. Sin optimización estática incluso cuando el tipo se conoce.

### 5.5 RTTI (`is`/`as`)

`generate_hulk_instanceof_body` escribe el cuerpo LLVM de `hulk_instanceof(obj: i8*, target_type_id: i32) -> i1`: loop while(vtable != null) que compara `vtable->type_id`. Si coincide `true`, si no sube por `parent_vtable`. `visit_as` (`llvm_visitor.rs:1271-1386`) invoca el chequeo y aborta con `printf` + `exit(1)` si falla.

### 5.6 For sobre Iterable

`visit_for` (`llvm_visitor.rs:802-954`): evalúa el iterable, chequea si tiene `iter()` (protocolo Enumerable) para obtenerlo o usa el valor directo, y loop virtual con `next()` y `current()`. Uniforme para `_Range` y iterables definidos por usuario.

### 5.7 Operadores binarios

`visit_binary_op` (`llvm_visitor.rs:300-321`): `&` y `|` se compilan a `build_and`/`build_or` de LLVM sobre `i1`, es decir **evaluación estricta, no cortocircuito**. Ambos operandos siempre se computan. Aritmética: `f64` con instrucciones nativas; `^` invoca `pow`. Comparaciones: `fcmp` para floats, `icmp` para booleanos.

### 5.8 Built-ins

`declare_all_builtins`: `sin`, `cos`, `sqrt`, `exp`, `log`, `pow`, `fmod`, `rand`, `printf`, `puts`, `exit`, `malloc`. `compile_print_call` selecciona formato según tipo. `compile_range_call` construye `_Range` alineado con protocolo `Iterable`.

---

## 6. Features opcionales

Marcadas y verificadas:

- **Sistema de tipos**: unificación, sustitución, occurs-check, constraints diferidas, instanciación fresca, monomorfización. Implementado correctamente.
- **Chequeo de tipos**: cinco fases, acumulación de errores, LCA para `if`, conformancia estructural a protocolos. Implementado.
- **OOP con herencia**: herencia simple con `inherits`, atributos y métodos aplanados, VTables, `self` y `base`. Implementado.
- **Polimorfismo con `is`/`as`**: RTTI vía `hulk_instanceof`. Implementado.
- **Iterables y protocolo `Iterable`**: protocolo registrado, `T*` como azúcar, `for` desugarizado en codegen. Implementado end-to-end.
- **Protocolos con conformancia estructural**: implementado.

No marcadas y no implementadas: arrays, lambdas, macros. Sin token, sin nodo, sin gramática, sin codegen.

---

## 7. Exactitud del reporte

### 7.1 Claims verificados

Parser LALR(1) con LALRPOP; lexer basado en Thompson; type inference HM-lite; monomorfización; VTables uniformes para dispatch y RTTI; protocolos estructurales; `for` a través de `Iterable`; `T*` como azúcar sintáctica.

### 7.2 Discrepancias

- **Operadores lógicos**: el reporte no aclara si `&`/`|` cortocircuitan. El codegen NO cortocircuita.
- **Detección de ciclos de herencia**: no implementada, el reporte sugiere robustez completa.
- **Monomorfización de `For`**: brazo vacío + `todo!()` en casos no manejados.
- **Comentarios**: el lexer solo maneja `//`, no `#`. Si tests usan `#`, fallará.

### 7.3 Reconocimiento honesto

El reporte admite explícitamente que **no soporta vectores/arrays**, consistente con el código.

---

## 8. Diagnóstico de fallas principales

### 8.1 Arrays

Sin token `[`, sin nodo AST, sin gramática ni codegen. Cualquier test con arrays falla en lexer (`LEXICAL: Carácter no reconocido: '['`).

### 8.2 Lambdas

Sin nodo `Lambda`, sin gramática. Tests con funciones anónimas fallan en parser (`SYNTACTIC: Unrecognized token: LParen`).

### 8.3 Macros

Sin nodo, sin sintaxis. Fallos esperados en `ok/macros/`.

### 8.4 for_even_count

Similar a #47 y #48: la expresión `if` como operando de `+` no está soportada por la gramática (`SYNTACTIC: Unrecognized token: If`).

### 8.5 Fallos latentes internos

- Operadores lógicos sin cortocircuito: efecto observable solo si hay side-effects.
- Ciclos de herencia: cuelga el compilador.
- Monomorfización de `for` genérico: no propaga sustituciones.

### 8.6 Interpretación global

El compilador implementa un núcleo sólido: aritmética, control de flujo, OOP con herencia y polimorfismo dinámico, protocolos estructurales, iterables genéricos y RTTI. Las fallas de CI se explican por decisiones deliberadas del equipo de **no abordar arrays, lambdas ni macros** y por pequeños agujeros en el semantizador. Los descuentos por CI deben pesarse contra la calidad conceptual del núcleo.
