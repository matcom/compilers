---
student: Amircal Metelis (solo)
issue: 34
repo: amircalabel/Hulk-compiler
branch: main
date: 2026-07-02
---

# Evaluación técnica — Compilador HULK de Amircal Metelis

> Repositorio: https://github.com/amircalabel/Hulk-compiler
> Rama: main | Evaluación CI: 2026-06-30
> Generado por: Claude Code (evaluación automática)

---

## 1. Descripción arquitectónica

**Lenguaje y build.** El proyecto está escrito en C++17. Hay dos sistemas de build declarados: un `Makefile` en la raíz que hace `find src -name "*.cpp"` y compila todo con `g++ -std=c++17 -Wall -Wextra -O2` (`Makefile:15,45`), y un `CMakeLists.txt` que enumera explícitamente los `.cpp` a incluir (`CMakeLists.txt:42-84`). El contrato de evaluación exige `make build` → binario `./hulk` en la raíz, y el Makefile efectivamente apunta a `hulk` (`Makefile:12,35-38`).

**Estructura del árbol** (`src/`, 5744 LOC de C++ contando cabeceras):

| Módulo | Archivos | LOC | Rol declarado |
|--------|----------|-----|---------------|
| `scanner/` | `Scanner.{hpp,cpp}`, `Token.{hpp,cpp}` | ~440 | Análisis léxico manual |
| `parser/` | `Parser.{hpp,cpp}` | ~842 | Descenso recursivo estilo Pratt |
| `ast/` | `Expr.{hpp,cpp}`, `Stmt.{hpp,cpp}`, `AstPrinter.{hpp,cpp}` | ~466 | Jerarquía Visitor con `Expr`/`Stmt` |
| `resolver/` | `Resolver.{hpp,cpp}` | ~265 | Análisis de scopes estilo Lox cap. 11 |
| `type/` | `Type.{hpp,cpp}` | ~335 | `Type` con `Number/String/Boolean/Nil/Object/Class/Protocol/Function/Generic` |
| `inferer/` | `TypeInferer.{hpp,cpp}` | ~255 | Inferencia de tipos (sección A.9) |
| `interpreter/` | `Interpreter.{hpp,cpp}` | ~648 | Tree-walk interpreter (modo REPL) |
| `backend/vm/` | `VM.{hpp,cpp}`, `Value.{hpp,cpp}`, `CallFrame.{hpp,cpp}`, `OpCode.hpp`, `GC.hpp` | ~1514 | Máquina virtual de pila con NaN-boxing y GC |
| `backend/banner/` | `BannerIR.{hpp,cpp}`, `BannerGenerator.{hpp,cpp}` | ~875 | IR "BANNER" de tres direcciones |
| `backend/` | `ASTSerializer.{hpp,cpp}`, `CodeGenerator.{hpp,cpp}` | ~374 | Serializador AST + generador de C++ transpilado |

**Estilo de referencia.** El proyecto sigue muy de cerca la arquitectura y nomenclatura de "Crafting Interpreters" de Robert Nystrom (Lox): `Scanner`, `Parser` con Pratt, jerarquía `Expr`/`Stmt` con `visitor pattern`, `Resolver` (cap. 11), VM con `CallFrame`, upvalues y GC (caps. 14-26). Esto es una elección pedagógica legítima — el libro es material canónico. El problema, como se detalla más abajo, es que casi todo ese andamiaje está **desconectado del flujo real** que ejecuta `./hulk archivo.hulk`.

**Flujo real ejecutado.** Trazando `main.cpp:runFile()` (`src/main.cpp:153-185`), la pipeline efectiva de compilación es:

```
Fuente HULK → Scanner → Parser → CodeGenerator (transpilación a C++) → g++ → ./output
```

**No participan** en ese flujo: `Resolver`, `TypeInferer`, `Interpreter`, la VM completa, `ASTSerializer`, ni `BannerGenerator`/`BannerIR`. El `Interpreter` **solo** se instancia en modo REPL (`main.cpp:121-147`), que la interfaz del curso no evalúa. Grep sobre `src/main.cpp` confirma que solo se incluye `interpreter/Interpreter.hpp` y `backend/CodeGenerator.hpp`; no hay ningún `#include` de VM, Banner, Resolver o TypeInferer en el punto de entrada.

**El binario `./hulk` está commiteado al repo.** El único commit en `main` (SHA `3113860`, "Fix scanner source ownership...", 2026-06-30) versiona tanto el fuente como el binario compilado `hulk` (462 656 B) y `output` (29 568 B). Esto es lo que permite que el CI diga "✅ Build successful" pese a que `make build` **falla** localmente en un `Ubuntu 24.04` limpio (ver §6).

---

## 2. Scanner

Archivo: `src/scanner/Scanner.{hpp,cpp}`, `src/scanner/Token.{hpp,cpp}`.

**Enfoque.** Hand-written, un carácter por vez, patrón "maximal munch" para pares (`==`, `!=`, `<=`, `>=`, `:=`, `=>`, `@@`).

**Tokens declarados** (`Token.hpp:9-48`): `LEFT_PAREN`, `RIGHT_PAREN`, `LEFT_BRACE`, `RIGHT_BRACE`, `COMMA`, `DOT`, `MINUS`, `PLUS`, `SEMICOLON`, `SLASH`, `STAR`, `CARET` (^), `PERCENT` (%), `AT`, `AT_AT`, `VAR`, `ARROW` (`=>`), `DOLLAR`, `BANG`, `BANG_EQUAL`, `EQUAL`, `EQUAL_EQUAL`, `GREATER`, `GREATER_EQUAL`, `LESS`, `LESS_EQUAL`, `COLON`, `COLON_EQUAL`, `IDENTIFIER`, `STRING`, `NUMBER`, palabras clave (`LET`, `IN`, `FUNCTION`, `TYPE`, `PROTOCOL`, `DEF`, `IF`, `ELIF`, `ELSE`, `WHILE`, `FOR`, `RETURN`, `PRINT`, `NEW`, `INHERITS`, `SELF`, `BASE`, `IS`, `AS`, `TRUE`, `FALSE`, `NIL`) más `AND`, `OR`, `NOT` como palabras.

**Discrepancia observada — token `%`.** El código fuente actual (`Scanner.cpp:117`) sí despacha `case '%': addToken(TOKEN_PERCENT);`. Sin embargo, el binario checkeado en el repo **rechaza `%`** con `LEXICAL: unexpected character '%'` — verificado corriendo `./hulk` con un input `print(10 % 3);` (repro real: exit 65, mensaje `(1,11) LEXICAL: unexpected character '%'`). Esto significa que el binario commiteado fue compilado antes del arreglo, o desde otro tree. Es una discrepancia grave entre el código y el ejecutable que el CI corre.

**Modificadores de identificador.** El scanner acepta `$` como carácter de identificador (`Scanner.cpp:224,241`), presumiblemente para placeholders de macros. No hay `def`/`$name` funcional aguas abajo.

**Errores léxicos.** Se reportan con `(line,col) LEXICAL: <msg>` vía `lexicalError()` global (`main.cpp:55-57`). El código de salida se decide por `getExitCode()` (`main.cpp:96-101`) según qué flag se levantó primero. Cumple el contrato en el formato del mensaje y el exit-code.

**Cobertura.** Comentarios `//`, cadenas multi-línea sin escapes reales (el escaneo solo busca la comilla de cierre — no procesa `\n`, `\t`, `\"`), números enteros o decimales sin notación científica.

---

## 3. Parser

Archivo: `src/parser/Parser.{hpp,cpp}` (842 LOC).

**Enfoque.** Descenso recursivo con jerarquía manual de precedencias. Pese a que el `README`/`REPORT.MD` dice "Pratt parser", no hay tabla `ParseRule` — es descenso recursivo clásico con funciones por nivel:

| Nivel | Función | Operadores | Origen |
|-------|---------|------------|--------|
| 1 | `expression` → `assignment` | `:=` | `Parser.cpp:513-524` |
| 2 | `logicalOr` | `or`, `\|` | `L526-534` |
| 3 | `logicalAnd` | `and`, `&` | `L536-544` |
| 4 | `equality` | `==`, `!=` | `L537-544` (aprox.) |
| 5 | `comparison` | `<`, `<=`, `>`, `>=` | ídem |
| 6 | `term` | `+`, `-` | ídem |
| 7 | `factor` | `*`, `/`, `^` | `L555-563` |
| 8 | `concat` | `@`, `@@` | `L565-573` |
| 9 | `unary` | `!`, `-` prefijos | `L575-582` |
| 10 | `call` | `f(...)`, `.` | `L584-598` |
| 11 | `primary` | literales, ids, `let`, `if`, `print`, `(...)`, `{...}` | `L600-639` |

**Problemas graves de gramática HULK.**

1. **`print` está en el nivel de statement Y de expresión.** El scanner emite `TOKEN_PRINT` como keyword; el parser lo consume en `statement()` (`Parser.cpp:272-274`) como statement Lox-style `print expr;`. Pero *también* está manejado en `primary()` (`L618-627`) — un fallback para no confundirlo con identificador. Al llegar el ejemplo canónico HULK `print(42);`:
   - `statement()` matchea `TOKEN_PRINT`
   - `printStatement()` llama `expression()` con el resto: `(42);`
   - `expression()` desciende a `primary()`, ve `(`, llama `parseParenthesizedExpression()` → `GroupingExpr(LiteralExpr(42))`
   - Consume `;` — OK
   - Resultado: `PrintStmt(GroupingExpr(LiteralExpr(42)))`

   El CodeGenerator **no maneja `GroupingExpr`** (§ 5), por lo que emite `nullptr` → salida "nil".

2. **`function f(...) => expr` sí está soportado** (`Parser.cpp:341-348`) — inline arrow bodies.

3. **`let x = ..., y = ..., z = ... in expr`** soportado con `,` (`L646-660`).

4. **`if (c) e1 else e2`, `elif`** soportado como expresión en `ifExpression()` (`L662-681`).

5. **`type Name(args) { attrs; methods() { ... } }`** parseado en `classDeclaration()` (`L360-...`), con `inherits Padre(args)`.

6. **Estructura general.** El parser reconoce **casi toda la gramática HULK sintácticamente** — el AST se construye para `let`, `if`, `while`, `for`, `type`, `function`, `new`, `self`, `base`, protocolos. La falla no es en el parseo, es aguas abajo.

**Reporte de errores.** Formato `(line,col) SYNTACTIC: <msg>` (`Parser.cpp:57-69`, `main.cpp:59-61`). La `col` es siempre `0` porque `Token` no lleva columna (`Parser.cpp:62`). Cumple el contrato en el prefijo `SYNTACTIC:` pero pierde información posicional útil.

**Recuperación.** Panic-mode con `synchronize()` (`L75-94`) — busca `;` o keyword de nivel-statement. Es suficientemente conservador para no explotar, aunque no muy fino.

---

## 4. AST + Resolver + TypeInferer

**AST.** Dos jerarquías separadas: `Expr` (`ast/Expr.hpp:198 LOC`) con `LiteralExpr`, `BinaryExpr`, `UnaryExpr`, `GroupingExpr`, `VariableExpr`, `AssignExpr`, `LetExpr`, `IfExpr`, `WhileExpr`, `ForExpr`, `BlockExpr`, `CallExpr`; `Stmt` (`ast/Stmt.hpp:209 LOC`) con `ExpressionStmt`, `PrintStmt`, `ReturnStmt`, `BlockStmt`, `VarDeclStmt`, `FunctionDeclStmt`, `ClassDeclStmt`, `ProtocolDeclStmt`, `MacroDeclStmt`, `IfStmt`, `WhileStmt`, `ForStmt`. Ambas jerarquías implementan `visitor pattern` con métodos `accept()`.

**Duplicidad `Expr`/`Stmt`.** El diseño duplica constructos (hay tanto `IfStmt` como `IfExpr`, tanto `WhileStmt` como `WhileExpr`, etc.). En HULK todo es expresión — no hay `IfStmt` — pero el proyecto arrastra la separación Lox. Esto **no rompe nada por sí solo**, pero complica downstream: los visitors deben implementar ambos, y en la práctica solo el CodeGenerator se preocupa por unos pocos statements.

**Resolver — no compila.** `src/resolver/Resolver.cpp` **no compila** en un build limpio (`make build 2>&1`):

```
src/resolver/Resolver.cpp:18:12: error: 'class std::vector<...>' has no member named 'push'
src/resolver/Resolver.cpp:22:12: error: 'class std::vector<...>' has no member named 'pop'
src/resolver/Resolver.cpp:27:12: error: 'class std::vector<...>' has no member named 'top'
src/resolver/Resolver.cpp:32:12: error: 'class std::vector<...>' has no member named 'top'
```

`scopes` está declarado como `std::vector<std::unordered_map<std::string, bool>>` (`Resolver.hpp:64`) pero el `.cpp` lo usa como si fuera `std::stack` (`push({})`, `pop()`, `top()[...]` — `Resolver.cpp:17-33`). El bug es trivial de arreglar (`push_back`, `pop_back`, `back()`) pero rompe el build completo del Makefile en cualquier host que no tenga el binario ya compilado.

**TypeInferer.** `TypeInferer.{hpp,cpp}` existe con 255 LOC — implementa la sección A.9 según el REPORT — pero **nunca se instancia ni se llama** desde `main.cpp`. Es código muerto respecto al pipeline real.

---

## 5. Backend: VM + GC + BANNER + CodeGenerator

El "backend" tiene **cuatro sub-piezas** que compiten:

### 5.1 VM de pila con GC — completamente desconectada

`src/backend/vm/VM.{hpp,cpp}` (~1037 LOC), `Value.{hpp,cpp}`, `CallFrame.{hpp,cpp}`, `OpCode.hpp`, `GC.hpp`. Implementa:

- Stack de valores + call stack (`VM.hpp:107-131`).
- `Value` con NaN-boxing declarado (`Value.hpp`, 191 LOC).
- Bucle principal `VM::run()` con `switch` sobre `OpCode` (~15 opcodes: `OP_CONSTANT`, `OP_ADD`, `OP_SUB`, `OP_MUL`, `OP_DIV`, `OP_NEGATE`, `OP_PRINT`, ...).
- `defineBuiltins()`, string interning, upvalues para closures, GC mark-sweep (`GC.hpp`, 44 LOC).

**Nunca se instancia.** Un `grep -n "VM" src/main.cpp` da cero resultados. Ningún `.cpp` fuera de `backend/vm/` referencia `VM::`, `VM(...)`, `interpret(`, ni `run()`. El bloque completo es **código huérfano**.

### 5.2 BANNER IR — desconectado

`src/backend/banner/BannerIR.{hpp,cpp}` + `BannerGenerator.{hpp,cpp}` (~875 LOC). Declara secciones `.TYPES`, `.DATA`, `.CODE`, instrucciones `LOAD`, `STORE`, `ADD`, `SUB`, ..., `ALLOCATE`, `GETATTR`, `SETATTR`, `LABEL`, `GOTO`, `IF_GOTO`, `PARAM`, `CALL`, `VCALL`, `RETURN`. El `BannerGenerator` es un `ExprVisitor + StmtVisitor` completo.

**Nunca se usa.** Igual que la VM: no hay `#include` desde `main.cpp` ni instanciación. Además, `BannerGenerator.hpp` incluye `resolver/Resolver.hpp` e `inferer/TypeInferer.hpp` — si se conectara, arrastraría los errores de compilación del Resolver.

### 5.3 CodeGenerator — el único conectado — es un stub

`src/backend/CodeGenerator.{hpp,cpp}` (~282 + 28 LOC). **Este es el único componente del "backend" que efectivamente se ejecuta.** El plan:

1. Emitir un archivo `output.cpp` con `RUNTIME_HEADER` (`CodeGenerator.cpp:12-146`) — 130 LOC de C++ que definen `HulkValue` como `std::variant<double, std::string, bool, std::nullptr_t, Obj*>`, funciones `stringify`, `add`, `subtract`, `multiply`, `divide`, y un `Environment` con `define`/`get`/`assign`.
2. Envolver los statements del programa fuente traducidos en `int main() { ... }`.
3. `system("g++ -std=c++17 -O2 output.cpp -o output")` (`L266-267`).
4. `chmod 0755` + borrar `output.cpp`.

**Cobertura real del CodeGenerator** (`generateStatement`, `generateExpression`, `literalToValueExpr`, `L181-236`):

| Constructo AST | ¿Traducido? |
|----------------|-------------|
| `PrintStmt` | Sí — emite `std::cout << stringify(...) << std::endl;` |
| `ExpressionStmt` | Sí — emite `<expr>;` |
| Todo lo demás (`VarDeclStmt`, `FunctionDeclStmt`, `IfStmt`, `WhileStmt`, `ForStmt`, `ReturnStmt`, `BlockStmt`, `ClassDeclStmt`, ...) | **No** — devuelve `"    // Unhandled statement type\n"` (`L192`) |
| `LiteralExpr` | Sí |
| `BinaryExpr` con `+`, `-`, `*`, `/` | Sí |
| `BinaryExpr` con `^`, `%`, `@`, `@@`, `==`, `!=`, `<`, `<=`, `>`, `>=`, `and`, `or`, `&`, `\|` | **No** — cae al `default: return left;` (`L211`) — silenciosamente devuelve solo el operando izquierdo. |
| `UnaryExpr` (`!`, `-`) | **No** — no hay caso, cae a la última rama de `generateExpression` que devuelve `"nullptr"` (`L220`) |
| `GroupingExpr` `(...)` | **No** — cae al `return "nullptr"` |
| `VariableExpr` | Sí, pero solo emite `env->get("nombre")` sin ninguna `env->define()` correspondiente (nunca hay declaración de variables en el output) — siempre resuelve a `nullptr`. |
| `AssignExpr`, `LetExpr`, `IfExpr`, `WhileExpr`, `ForExpr`, `BlockExpr`, `CallExpr` | **No** — todos caen a `return "nullptr"` |

**Consecuencias observadas en pruebas locales del binario checkeado.**

Corriendo `./hulk <file>` seguido de `./output` sobre los tests que el estudiante incluyó en `tests/input/` (que son C-like `print 42;`, no HULK real):

| Test estudiante | Resultado |
|-----------------|-----------|
| `01_literals.hulk` (`print 42;` etc.) | Sale `42\n3.141600\nHello, World!\ntrue\nfalse\nnil` — literales funcionan porque `LiteralExpr` sí está soportado |
| `02_arithmetic.hulk` (`print 1+2; print 2^3; print (1+2)*3;`) | `3, 7, 20, 5, 2, nil, 7` — `+`, `-`, `*`, `/` funcionan; `^` devuelve el operando izquierdo (2); `(1+2)*3` devuelve `nil` porque `GroupingExpr` no está soportado |
| `03_strings.hulk` (`print "Hello" @ " " @ "World";`) | `Hello` — `@` no está soportado, se pierden los operandos derechos |
| `04_variables.hulk` (`let x = 42 in print x;`) | `(2,0) SYNTACTIC: Expect expression. at 'print'` |
| `06_if.hulk` (`let x = 5 in { if ... }`) | `(2,0) SYNTACTIC: Expect expression. at '{'` |
| `09_functions.hulk` (`function add(a, b) => a+b;`) | `(2,0) SYNTACTIC: Expect '{' before function body. at '='` (¡pero `Parser.cpp:341` sí matchea `TOKEN_ARROW`! discrepancia binario vs. código) |

Sobre los tests reales del CI del curso (`tests/hulk/ok/minimal/`):

| Test CI | Resultado esperado | Resultado real |
|---------|--------------------|----------------|
| `hello.hulk` (`print("Hello, World!");`) | `Hello, World!` | `nil` (parser envuelve el string en `GroupingExpr`; CodeGen devuelve `nullptr`) |
| `arithmetic.hulk` (con `%` y `^`) | `ok\nok\nok\nok\nok` | `LEXICAL: unexpected character '%'` — exit 65 |
| `block_value.hulk` (`{ if (...) print(...) else print(...); ... }`) | `ok\nok` | `SYNTACTIC: Expect expression. at '{'` — porque `statement()` empieza con `{` y va a `blockStatement()`, pero el contenido usa `if` como expresión, cosa que `expressionStatement()` maneja de otro modo. |

### 5.4 GC — declarado, nunca ejecutado

`GC.hpp` (44 LOC) declara la interfaz. Es solo un envoltorio del GC de la VM. Como la VM no se ejecuta, el GC tampoco.

---

## 6. Análisis de fallas totales (0/71 en CI)

**Reporte del CI del 2026-06-30 21:23 UTC** (último `/regrade` del estudiante):

| Categoría | Passed | Total | Estado |
|-----------|--------|-------|--------|
| `ok/minimal` | 0 | 20 | ⚠️ |
| `ok/types` | 0 | 10 | ⚠️ |
| `ok/oop` | 0 | 10 | ⚠️ |
| `errors/lexical` | 0 | 6 | ⚠️ |
| `errors/syntactic` | 0 | 10 | ⚠️ |
| `errors/semantic` | 0 | 15 | ⚠️ |
| `ok/extras` | 0 | 10 | ➖ (bonus) |
| **Total obligatorios** | **0** | **71** | **FAIL** |

**Distribución de modos de fallo** (analizando las 20 fallas de `ok/minimal` del comentario CI):

- **`compilation failed (exit 65)`**: 17/20 tests — el parser rechaza el fuente. Motivos:
  - Uso de `%` operador (lexical error del binario checkeado).
  - `let x = ... in { block }` — el parser no procesa el `{` como `BlockExpr` en ese contexto (el bloque como expresión sí existe en `blockExpression()` pero solo se dispara desde `primary()`, no como cuerpo de `let ... in`; la ruta que sí funciona es `statement() → blockStatement()`, que no es una `Expr`).
  - `function f(): T { ... }` — anotaciones de retorno probablemente parseadas OK pero el binario checkeado no coincide con el `.cpp` actual.
  - `if (c) e1 else e2` como sub-expresión (soportado en el código de `primary()` pero probablemente rota por interacción con el resto).

- **`expected [X] got [nil]`**: 3/20 tests — el compilador compila y genera `./output`, pero el output ejecuta y emite `nil`. Causa raíz: `CodeGenerator` sólo maneja 5 tipos de nodo AST (§5.3). Todo lo demás emite `nullptr` como valor. Los ejemplos:
  - `hello`: `print("Hello, World!")` → `nil` (por `GroupingExpr`).
  - `conditionals`: espera `negative\nzero\npositive`, obtiene vacío (llamadas a función no manejadas).
  - `strings`: `print("Hello, World!")` + `print("foo" @ "bar")` → vacío/parcial.

**Raíz técnica de las 71 fallas.**

1. **CodeGenerator es un stub de 282 LOC** que solo cubre `print`, literales y las cuatro operaciones aritméticas básicas. Es incapaz de compilar el 95 % de la gramática HULK que sí *parsea*.
2. **La verdadera lógica de ejecución** (`Interpreter.cpp`, 529 LOC, con `visitIfExpr`, `visitLetExpr`, `visitWhileExpr`, `visitCallExpr`, etc.) **existe** — pero está enchufada solo en el modo REPL, no en `runFile()`.
3. **La VM y el BANNER IR nunca se conectaron** al pipeline. Son islas de código bien escrito (aparentemente siguiendo el libro de Nystrom capítulos 14-26) que nunca se llegan a instanciar.
4. **El Resolver está roto** y el build limpio del Makefile falla con 4 errores de tipo (`std::vector` vs `std::stack` API). El CI pasa la fase de build porque el `./hulk` está pre-compilado y commiteado al repo.
5. **Discrepancias entre el código fuente y el binario checkeado**: el fuente actual dispatchea `%` como `TOKEN_PERCENT` y acepta `function f() => expr`, pero el binario checkeado rechaza ambos. El binario fue compilado con un fuente anterior.

---

## 7. Discrepancia REPORT.md vs REPORT.MD (case-sensitivity)

El archivo existe como `REPORT.MD` (mayúsculas) — 14 293 B, 365 líneas, en la raíz del repo. El grader lo busca como `REPORT.md` (`.github/workflows/grade.yml:123`) mediante `if [ -f REPORT.md ]`, que en Linux (case-sensitive) **no matchea** `REPORT.MD`. Por eso el CI reporta:

> ### 📄 Report
> ❌ `REPORT.md` not found in repo root.

Es un fallo trivial de corregir: `git mv REPORT.MD REPORT.md`. Aun corregido, el reporte tendría otro problema (§ 8): **describe un compilador que no existe**.

---

## 8. Estado real del compilador vs. lo que el REPORT afirma

El `REPORT.MD` (365 líneas, ~2 400 palabras) describe con detalle una arquitectura completa: pipeline `Scanner → Parser → Resolver → TypeInferer → Backend`, con backend "BANNER IR + VM con NaN boxing y GC mark-sweep". **Casi todo lo descrito no participa en el flujo real** que ejecuta `./hulk archivo.hulk`. La discrepancia es sistemática:

| Sección del REPORT | Estado real |
|--------------------|-------------|
| §2.1 "Estructura de directorios" | Coincide con la estructura física. OK. |
| §2.2 "Backend BANNER" — `BannerIR.hpp/cpp`, `BannerGenerator.hpp/cpp` | Los archivos existen (~875 LOC) pero **nunca se instancian ni se referencian** desde `main.cpp` u otro `.cpp` fuera de `backend/banner/`. |
| §2.2 "VM" — `VM.hpp/cpp`, `Value.hpp/cpp`, etc. | Existen (~1500 LOC) pero **nunca se instancian**. `grep VM src/main.cpp` da 0 resultados. |
| §2.2 "CodeGenerator" — "produce ejecutable" | Sí existe y se llama, pero solo cubre 5 nodos AST (§5.3). |
| §3.4 "Resolver — recorre el AST y conecta cada uso con su declaración" | **No compila** el `.cpp` (4 errores de tipo). El REPORT lo describe como si funcionara. |
| §3.5 "TypeInferer — implementa A.9.2, A.9.3, A.9.5, LCA" | Existe (~255 LOC) pero **nunca se instancia** desde `main.cpp`. |
| §4.1 "BANNER IR — .TYPES, .DATA, .CODE" | El `BannerIR.cpp` implementa las estructuras, pero **no se ejecuta**. |
| §4.2 "VM stack-based, NaN boxing, upvalues, GC mark-sweep" | Todo declarado en código, **nada instanciado**. |
| §4.3 "CodeGenerator — dos pasos, output.cpp + g++" | Cierto, pero omite que solo maneja 5 nodos AST. |
| §5.1 "Expresiones — aritméticas, `@`, `&`, `\|`, `!`, comparación, `:=`, `let ... in`, `if/elif/else`, `while`, `for`, bloques" | **Parseables sintácticamente** en muchos casos, pero **el CodeGenerator no las traduce**. Corren en el Interpreter (que solo se usa en REPL). |
| §5.2 "Statements — print, return, bloques, funciones, clases, protocolos, macros" | Sólo `print` y `expression` se traducen a C++. Todos los demás → `// Unhandled statement type`. |
| §7 "Limitaciones conocidas — funciones nativas, módulos, optimizaciones, vectores, functores, macros" | La lista de limitaciones es **muy optimista** — el compilador realmente no ejecuta `if`, `while`, `let`, `function`, `class`, `protocol`, `type`, ni cualquier concatenación de strings. |
| §8 "Pruebas — 14 pruebas en `tests/input/`" | Los tests existen. Pero **12 de 14** fallan al ejecutar en el binario del propio estudiante (verificado ejecutando `for f in tests/input/*.hulk; do ./hulk $f && ./output; done`). |
| §10 "Ejemplo de compilación factorial → salida esperada 1,1,2,6,24,120" | **Falso**. El compilador rechaza el archivo con `SYNTACTIC: Expect expression. at 'return'` en línea 4. |

El REPORT parece haber sido escrito **antes** de que la ejecución end-to-end estuviera funcionando, y no fue actualizado con la realidad.

---

## 9. Diagnóstico y conclusión

**Fortalezas del proyecto.**

1. **Ambición arquitectónica.** El código sí trae los skeleton de Scanner, Parser, AST con Visitor, Resolver, TypeInferer, VM con NaN-boxing, GC, CallFrame, upvalues y BANNER IR. Alguien invirtió tiempo escribiendo todos esos módulos siguiendo el patrón didáctico canónico ("Crafting Interpreters" caps. 1-26).
2. **El Parser tiene alcance real.** Reconoce sintácticamente `let`, `if/elif/else`, `while`, `for`, `function` (inline y bloque), `type`, `protocol`, `def`, `new`, `inherits`, `self`, `base`, `is`, `as`, `:=`, `@`, `@@`. Un parser aislado que consumiera HULK y emitiera el AST cubriría probablemente el 70-80 % de la gramática.
3. **El Interpreter (`Interpreter.cpp`, 529 LOC) tiene lógica genuina** para `visitLetExpr`, `visitIfExpr`, `visitWhileExpr`, `visitVariableExpr`, `visitAssignExpr`, aritmética con coerciones, `ReturnException` para retorno anticipado. En modo REPL probablemente ejecutaría muchos programas.

**Puntos débiles.**

1. **El pipeline principal no funciona.** El `CodeGenerator` es un stub de 5 tipos de AST. Todo el trabajo del Parser, Interpreter, VM, BANNER y Resolver **no llega al output**. El resultado son 0/71 tests obligatorios pasados.
2. **El código no compila en un host limpio** (`Resolver.cpp` — 4 errores de API `stack` vs `vector`). El CI solo pasa el `build` porque el binario está commiteado; en la próxima máquina, `make build` fallará.
3. **El binario checkeado y el código fuente están desincronizados** (el binario rechaza `%`, el fuente lo acepta; el binario rechaza `function ... =>`, el fuente lo acepta).
4. **El REPORT.MD** — además del error de nomenclatura que lo hace invisible al CI — describe funcionalidades que no funcionan y omite que solo 5 nodos AST se traducen. El ejemplo del factorial en §10 es falso.
5. **Los propios tests del estudiante** (`tests/input/01_literals.hulk`..`14_math_utils.hulk`) están escritos en sintaxis **Lox** (`print 42;`, `type Point(x,y) { x = x; ...}`, `function f(a, b) => a+b;`), no HULK. Y aun así, 12 de 14 fallan.
6. **Ausencia de features opcionales.** El proyecto marca en el issue solo `[x] minimal` y `[x] types`. OOP, iterables, vectors, protocols, functors, macros están todos como `[ ]`. En la práctica, ninguno de los "obligatorios" (minimal + types) tampoco funciona.

**Conclusión.** El repositorio contiene el **andamiaje** de un compilador HULK con influencia clara de "Crafting Interpreters", con ~5 700 LOC repartidos en 8 módulos. Es un ejercicio pedagógicamente legítimo — el libro es un buen punto de partida. Pero el compilador **no funciona**: el flujo real termina en un stub de traducción a C++ que solo cubre `print(literal)` y las cuatro aritméticas básicas. Todo el resto del código (Interpreter, VM con GC, BANNER IR, Resolver, TypeInferer) está desconectado del punto de entrada `main::runFile()`. El REPORT.MD, aparte del error de mayúsculas en la extensión, describe un compilador que no existe.

En su estado actual el proyecto no cumple los objetivos del contrato de la evaluación automática (0/71 tests obligatorios). El estudiante tendría que:

1. Renombrar `REPORT.MD` → `REPORT.md`.
2. Arreglar los 4 errores en `Resolver.cpp` (o excluirlo del `find` en el Makefile).
3. Conectar el `Interpreter` — ya escrito — al flujo de `runFile()`, o bien invertir en llenar el CodeGenerator para que traduzca los ~15 tipos de AST que le faltan.
4. Reescribir el REPORT.md para describir lo que efectivamente ejecuta el compilador, no lo que estaba planeado.
