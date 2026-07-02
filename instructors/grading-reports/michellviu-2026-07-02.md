# Reporte Técnico Detallado — Michell Viu Ramirez (C-411)

> Repositorio: https://github.com/michellviu/HULK-Compiler  
> Rama: main | Evaluación: 2026-07-02  
> Generado por: Claude Code (evaluación automática)

---

## Bloque 1 — Arquitectura

**Lenguaje y herramientas de construcción.** El compilador está escrito en Rust (edition 2024) usando Cargo. Se divide en dos crates: `parser` (crate de librería en `src/parser/`) y `hulk_compiler` (binario en `src/`). El crate de parser incluye una gramática LALRPOP, el AST, el análisis semántico y cuatro módulos separados de análisis semántico. La generación de código usa la crate `inkwell` (versión 0.5, feature `llvm18-0`), un wrapper seguro de LLVM. El proceso de compilación completo es: `make build` → `cargo build` → copia a `./hulk`.

**Lexer y parser.** El lexer y parser se generan con LALRPOP a partir de una gramática LALR(1) en `src/parser/src/grammar.lalrpop`. El análisis léxico se define mediante el bloque `match` de LALRPOP que establece prioridades: keywords > operadores multicarácter > operadores simples > regex (NUMBER, STRING, ID). No existe lexer manual separado; LALRPOP genera todo el frontend. Los tokens de posición se producen automáticamente por LALRPOP (`@L`/`@R`).

**AST.** El AST es inmutable una vez construido. Está estructurado en módulos bajo `src/parser/src/ast/`: `atoms/` (literales, identificadores, grupos), `expressions/` (cada variante tiene su propio archivo: `if_expr.rs`, `let_expr.rs`, `for_expr.rs`, etc.), `declarations/` (clases, funciones, métodos, atributos). Hay un visitor pattern implementado en `src/parser/src/ast/visitor/visitor.rs` con un trait `Visitor` de ~30 métodos y una implementación `AstPrinterVisitor`. Los nodos del AST **no tienen información de tipo** directamente; los tipos viven en la `SymbolTable`.

**Pasadas semánticas.** Se implementan cuatro pasadas secuenciales:
1. `src/parser/src/semantic/collector.rs` — registra todas las declaraciones de clases y funciones, resuelve jerarquía de herencia (con detección de ciclos) y firmas de constructores.
2. `src/parser/src/semantic/semantic_checker.rs` — valida scoping, resolución de nombres, aridad, `self` fuera de métodos, firmas de override, genera warnings de variables no usadas.
3. `src/parser/src/semantic/type_inferer.rs` — inferencia de tipos por restricciones de uso para parámetros sin anotación. Usa lista de constraints y LCA para resolución.
4. `src/parser/src/semantic/type_checker.rs` — verificación de tipos completa: operadores, condiciones boolean, asignaciones, retornos, subtype conformance.

**Backend de generación de código.** Se usa LLVM vía inkwell. La generación produce un archivo objeto nativo (`.o`) que se enlaza con el runtime C (`runtime/hulk_runtime.c`) usando `cc`. El backend no usa JIT; compila a nativo directamente. El runtime C provee: print, matemáticas (conecta a libm), concat de strings, alloc (wrapper de calloc), conversiones número/bool→string, range iterable, y manejo de errores de cast.

**Gestión de memoria.** Los objetos en heap se asignan con `hulk_alloc` (calloc). No hay garbage collector; hay leaks en strings de concatenación y objetos de clase. Las variables locales usan `alloca` en el entry block de cada función (patrón SSA correcto).

**Features opcionales con estado:**

| Feature | AST | Semántico | Codegen |
|---------|-----|-----------|---------|
| for/range | Sí (`ForExpr`) | Sí (solo Range) | Sí (solo Range) |
| is / as | Sí (`IsExpr`, `AsExpr`) | Sí | Sí (type_id en slot 1) |
| case/of | Sí (`CaseExpr`) | Sí | **Stub — no genera código** |
| arrays (`new T[n]`) | Sí (`NewArray`) | Parcial | **No (TODO)** |
| vectores/index `[]` | Sí (`IndexAccess`) | Parcial | **No (TODO)** |

---

## Bloque 2 — Lexer

El lexer es generado por LALRPOP. Todos los tokens se definen en `src/parser/src/grammar.lalrpop:L11–33`.

**Operadores.** Todos los operadores del lenguaje están definidos. Operadores multicarácter `@@`, `:=`, `==`, `!=`, `<=`, `>=`, `=>` tienen prioridad sobre los simples (`grammar.lalrpop:L18`). Operadores simples: `+`, `-`, `*`, `/`, `%`, `^`, `<`, `>`, `&`, `|`, `!`, `@`, `=`, `.`, `,`, `:`, `;`, `(`, `)`, `{`, `}`, `[`, `]` (`grammar.lalrpop:L21–24`). Los comentarios (`#`) **no están definidos** en el bloque match y causarían un error léxico. Las pruebas del curso no usan comentarios, por lo que no afecta los tests.

**Regex de identificadores.** `r"[a-zA-Z][a-zA-Z0-9_]*"` (`grammar.lalrpop:L32`). Correcto según especificación.

**Regex de números.** `r"[0-9]+(\.[0-9]+)?"` (`grammar.lalrpop:L30`). Acepta enteros y floats. No soporta notación científica ni `_` separadores.

**Strings con escapes.** `r#""([^"\\]|\\.)*""#` (`grammar.lalrpop:L31`). El patrón `\\.` acepta backslash seguido de **cualquier carácter**, incluyendo escapes inválidos como `\q`. El lexer acepta secuencias de escape inválidas sin error.

**Posiciones.** LALRPOP produce offsets que se convierten a línea/columna en `src/parser/src/tokens/position.rs`. Las posiciones en errores son correctas.

---

## Bloque 3 — Parser

**Niveles de precedencia reales en código:**

| Nivel | Regla | Operadores | Asoc. |
|-------|-------|------------|-------|
| 0 | `Expr` | `let`, `if`, `while`, `for`, `case` | N/A |
| 1 | `AssignExpr` | `:=` | Derecha |
| 2 | `OrExpr` | `\|` | Izquierda |
| 3 | `AndExpr` | `&` | Izquierda |
| 4 | `EqualityExpr` | `==`, `!=` | Izquierda |
| 5 | `ComparisonExpr` | `<`, `<=`, `>`, `>=` | Izquierda |
| 6 | `TypeTestExpr` | `is` | No encadenable |
| 7 | `CastExpr` | `as` | Izquierda |
| 8 | `ConcatExpr` | `@`, `@@` | Izquierda |
| 9 | `AdditiveExpr` | `+`, `-` | Izquierda |
| 10 | `MultiplicativeExpr` | `*`, `/`, `%` | Izquierda |
| 11 | `PowerExpr` | `^` | Derecha |
| 12 | `UnaryExpr` | `-`, `!` | Prefijo |
| 13 | `PostfixExpr` | `.`, `.()`, `[]` | Izquierda |
| 14 | `PrimaryExpr` | literales, ids, `new`, `()` | N/A |

Son **14 niveles** reales, no 15 como afirma el informe.

**Bug crítico — ordering de declaraciones.** La regla `Program: ClassDecl* FunctionDecl* EntryExpr?` (`grammar.lalrpop:L39–43`) obliga a que todas las clases precedan a todas las funciones. Si un archivo declara una función antes de un tipo, el parser reporta error sintáctico. Causa `ok/oop/constructor_expr: exit 2`.

**Bug crítico — if como operando.** `IfExpr` solo aparece en `Expr` (nivel máximo). No puede ser operando de `AdditiveExpr`. El test `for_even_count` usa `evens + if (i % 2 == 0) 1 else 0` que falla con `exit 2`.

**Dangling-else.** Resuelto por requerir `else` obligatorio; no existe `if` sin else. Correcto.

**Recuperación de errores.** No existe recuperación; el parser para al primer error de sintaxis. Los errores semánticos sí se acumulan.

---

## Bloque 4 — Análisis Semántico

**Tabla de símbolos** (`src/parser/src/semantic/symbol_table.rs`):
- `functions: HashMap<String, FuncInfo>` — funciones globales.
- `classes: HashMap<String, ClassInfo>` — clases con params, parent, atributos, métodos.
- `scopes: Vec<Scope>` — pila de scopes léxicos.

**Cross-references.** La pasada collector (`collector.rs:L19–38`) registra todo antes de analizar cuerpos. Funciones y clases pueden referenciarse sin orden de declaración — salvo la restricción gramatical de orden clases/funciones.

**Validación de scopes.** `semantic_checker.rs`: verifica variables declaradas (`L256–274`), `self` solo en métodos (`L259–261`), variables no usadas con warnings (`L563–570`).

**Aridad.** Verificada en pasada 2 para funciones, métodos y constructores.

**Inferencia de tipos.** `type_inferer.rs:L25–47`. Mecanismo: recolecta constraints del tipo `(param_name, HulkType)` basándose en uso del parámetro en operadores y llamadas. Resolución usa LCA para jerarquías de clase (`type_inferer.rs:L459–492`). No infiere tipos de variables `let` (solo parámetros y atributos de clase).

**Verificación de tipos.** `type_checker.rs`: aritmética requiere Number (`L301–330`), condiciones requieren Boolean (`L474–476`), LCA para ramas de if (`L480–499`), subtipado con `conforms_to` (`symbol_table.rs`).

**Detección de ciclos.** `collector.rs:L244–286`: chain-walk por cada clase con HashSet de visitados.

**Override signatures.** `semantic_checker.rs:L531–560`: verifica parámetros y tipo de retorno coincidan exactamente con padre.

**Múltiples errores semánticos.** Sí. Cada pasada acumula errores en `Vec<CompilerError>` y continúa.

---

## Bloque 5 — Generación de Código

**Tipos primitivos en LLVM** (`src/codegen/types.rs`):
- Number → `f64`
- Boolean → `i1`
- String → `ptr` (puntero opaco)
- Class → `ptr`

**Aritmética.** Usa instrucciones float (`fadd`, `fsub`, `fmul`, `fdiv`, `frem`) — `src/codegen/expressions.rs:L121–154`. Correcto para `Number = f64`.

**Comparaciones.** Todas usan `build_float_compare` con predicados OLT, OLE, OGT, OGE, OEQ, ONE — `src/codegen/expressions.rs:L173–245`. **Bug crítico:** `EqualEqual` llama `lhs.into_float_value()` incondicionalmente (`expressions.rs:L221–232`). Con operandos tipo puntero (strings, objetos) esto produce instrucción LLVM inválida → crash. Causa todos los exit 101.

**Operadores lógicos — NO hay short-circuit.** `expressions.rs:L248–258`:
```rust
tokens::BinOp::And(_) => {
    let v = self.builder.build_and(lhs.into_int_value(), rhs.into_int_value(), "and").unwrap();
    Some(v.into())
}
```
Evaluación eager. El informe afirma cortocircuito; el código es incorrecto.

**Control de flujo.** `if` genera bloques con PHI (`expressions.rs:L612–717`). `while` usa cond_bb/body_bb/merge_bb con alloca para preservar valor (`L722–768`). `for` llama a `hulk_range_next`/`hulk_range_current` del runtime (`L773–867`).

**OOP / VTable** (`src/codegen/classes.rs`):
- Layout struct: slot 0 = vtable ptr, slot 1 = type_id (i64), slots 2+ = atributos. `classes.rs:L131–171`.
- VTable global constante `__vtable_ClassName` con punteros a función. Overrides reemplazan entrada heredada. `classes.rs:L175–230`.
- Despacho dinámico: carga vtable desde slot 0, indexa por método, `build_indirect_call`. `expressions.rs:L1070–1141`.
- type_id para `is`/`as`: asignado en orden topológico (`classes.rs:L30–33`), comparado en `gen_is_type`.

**Bug OOP 1 — MemberAccess en infer_class_name.** `expressions.rs:L1253–1291`: no tiene caso para `MemberAccess`. Cuando el receptor de una llamada a método es un atributo (`self.wallet.deposit()`), devuelve None → despacho falla. Causa fallo en `class_interaction`.

**Bug OOP 2 — parámetros de método en symbols.** `gen_method_body` registra parámetros con `set_variable` (alloca scope) pero NO con `symbols.define_var`. `infer_class_name` llama `symbols.var_type("other")` → None → la expresión `other.x` produce None. Causa fallo en `vector_math`.

**Linking.** `codegen/mod.rs`: emite objeto `.o` con TargetMachine de LLVM, compila runtime.c con `cc`, enlaza con `-lm` → binario `./output`.

---

## Bloque 6 — Features Opcionales

**[x] Iterables / for loops:**
- AST: `ForExpr` con `var`, `iterable`, `body` — `ast/expressions/for_expr.rs`.
- Semántico: verifica que iterable sea `Range` — `type_checker.rs:L518–527`.
- Codegen: implementado para `Range`. Llama `hulk_range_next`/`hulk_range_current`.
- Tests: 9/10. Falla `for_even_count` por bug gramatical (if como operando de +).

**arrays (no marcado):**
- AST: `NewArray` existe — `ast/expressions/new_array.rs`.
- Codegen: no implementado (TODO).

---

## Bloque 7 — Precisión del Informe

**✅ Afirmaciones verificadas:**
- Layout VTable (slot 0/1/2+): `classes.rs:L131–171`. Correcto.
- Pasadas semánticas múltiples e independientes: verificado en 4 módulos.
- Inferencia por restricciones con LCA: `type_inferer.rs:L459–492`. Correcto.
- Detección de ciclos de herencia: `collector.rs:L244–286`. Correcto.
- Runtime en C con alloc, concat, cast_error: `runtime/hulk_runtime.c`. Correcto.
- Verificación de firma en override: `semantic_checker.rs:L531–560`. Correcto.

**❌ Afirmaciones incorrectas:**

1. **"Cortocircuito en operadores lógicos"** (REPORT.md, sección Generación de Código):
   > "Los operadores lógicos se implementan con cortocircuito cuando aplica, construyendo bloques de control para evaluar solo lo necesario."
   - Código: `expressions.rs:L248–258` — `build_and`/`build_or` directos (eager).
   - Clasificación: **Descripción incorrecta**.

2. **"15 niveles de precedencia"** (REPORT.md, sección Parser):
   > "La gramática de HULK define 15 niveles explícitos de precedencia para los operadores"
   - Código: 14 niveles reales en `grammar.lalrpop`.
   - Clasificación: **Inexacto** (error de conteo).

**⚠️ En código pero no en informe:**
- `case` expression: AST y semántica soportados, codegen es stub (`expressions.rs:L33–37`).
- PI = 3.14 y E = 2.71828 (valores imprecisos — `expressions.rs:L81–86`).
- Comentarios de línea `#` no están definidos en el lexer.
- Bug de ordering gramatical (clases antes que funciones).

---

## Bloque 8 — Diagnóstico de Fallas

| Test | Exit | Causa |
|------|------|-------|
| chained_elif | 101 | `==` entre strings llama `into_float_value()` en puntero |
| string_compare | 101 | Ídem |
| string_return | 101 | Ídem |
| polymorphism | 101 | Ídem (comparación en rama del método) |
| method_override | 101 | Ídem (retorno de método = puntero) |
| multilevel | 101 | Ídem |
| constructor_expr | 2 | Gramática: función antes de clase en archivo |
| for_even_count | 2 | Gramática: `if` no puede ser operando de `+` |
| class_interaction | runtime | `infer_class_name` no maneja MemberAccess |
| vector_math | runtime | Parámetros de método no en `symbols` |

Los 6 fallos con exit 101 tienen la misma raíz: el operador `==` asume siempre operandos numéricos. La corrección es verificar el tipo LLVM de `lhs` antes de elegir la instrucción de comparación (float vs. pointer → usar `icmp eq ptr` para strings/objetos).
