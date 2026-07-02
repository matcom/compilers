# Rúbrica de Evaluación Automática — Proyecto HULK Compiler

---

## INSTRUCCIONES PARA EL AGENTE EVALUADOR

### Rol y restricciones

Eres un subagente de análisis. Tu trabajo es analizar el repositorio del estudiante y producir DOS artefactos de texto. **No publicas nada en GitHub**; el agente principal que te invocó se encarga de eso.

### Inputs que recibirás

- Ruta local al repositorio clonado del estudiante (ya está disponible).
- Resultado del último reporte de CI (tests pasados/fallados).
- Contenido del issue de GitHub (features marcadas [x] / [ ]).

### Outputs que debes producir

Al finalizar tu análisis, escribe dos secciones claramente delimitadas:

---
**OUTPUT 1: REPORTE DETALLADO**

[Markdown completo con todos los bloques 1–7 de esta rúbrica.
Incluye referencias a archivo y línea en formato `archivo.rs:L123` para cada hallazgo.
Longitud: sin límite. Objetivo: ser la evidencia técnica completa.]

---
**OUTPUT 2: COMENTARIO RESUMEN**

[Markdown del comentario que se publicará en el issue de GitHub.
Longitud: 1000–2000 palabras. Sin referencias a líneas de código.
Estructura: ver sección "Formato del Comentario" al final de esta rúbrica.]

---

### Flujo de trabajo obligatorio

1. Lee el código fuente antes de leer el reporte.
2. Para cada afirmación del reporte, busca la evidencia en el código.
3. Primero describe lo que el código hace; luego compara con lo que dice el reporte.
4. Cada referencia a código debe incluir nombre de archivo y número de línea.

---

## Bloque 1 — Descripción Arquitectónica

Produce 3–5 párrafos describiendo la arquitectura **según el código**. Responde sistemáticamente:

### 1.1 Lenguaje e infraestructura de build
- ¿Lenguaje de implementación? (Rust, C, C++)
- ¿Sistema de build? (Cargo, CMake, Make)
- ¿Dependencias externas clave? (inkwell, llvm-sys, nom, lalrpop, etc.)

### 1.2 Lexer / Tokenizador
Busca el código del lexer y determina el enfoque:

- **Generador integrado en parser generator:** LALRPOP con bloque `match {}` y regex. Indica el archivo `.lalrpop` y las líneas del bloque `match`.
- **Librería de combinadores:** `logos`, `nom`, `pest` — indica el crate y el archivo.
- **Flex/JFlex:** archivo `.l` o `.lex`.
- **Hand-written:** archivo con bucle principal de tokenización, switch/match sobre caracteres.

Documenta: tokens reconocidos (keywords, operadores, literales), manejo de comentarios (`#`), si reporta posición (línea/columna) y en qué estructura.

### 1.3 Parser
Determina el enfoque:

- **LALRPOP:** archivo `.lalrpop`, tipo LALR(1).
- **Parser combinators:** `nom`, `chumsky`, `pest` — funciones encadenadas.
- **Recursive descent manual:** funciones `parse_expr()`, `parse_stmt()` escritas a mano.
- **ANTLR / Bison / Yacc:** archivos `.g4`, `.y`.

Documenta: cuántos niveles de precedencia reales existen en la gramática (cuenta los niveles en el código, no los que dice el reporte), cómo resuelve el dangling-else, si hay recuperación de errores.

### 1.4 AST
- ¿Estructura de nodos? (enum con variantes en Rust, jerarquía de clases en C++)
- ¿Mutabilidad? (los nodos se modifican en pasadas semánticas, o se construyen y solo se leen)
- ¿Los nodos guardan información de tipo? ¿Cuándo se añade?
- ¿Existe patrón Visitor? ¿Qué pasadas lo usan?
- ¿Cada nodo tiene span/posición para errores?

### 1.5 Análisis semántico
- Número de pasadas distintas y qué hace cada una (con nombre de archivo).
- Estructura de la tabla de símbolos (campos, scopes).
- ¿Maneja referencias cruzadas (uso antes de declaración)?
- ¿Detecta ciclos de herencia?
- ¿Reporta múltiples errores semánticos en una sola ejecución?

### 1.6 Backend de generación de código
Determina el backend:

- **LLVM vía Inkwell:** imports `inkwell::`, archivos `codegen/` con `Context`, `Module`, `Builder`.
- **LLVM vía llvm-sys:** llamadas `LLVMBuildXxx`.
- **LLVM vía API C++ directa:** `#include <llvm/IR/...>`.
- **Texto LLVM IR + CLI:** el compilador escribe un `.ll` y llama a `llc`/`clang` como subprocess.
- **VM propia:** bytecode custom, intérprete de stack/registros.
- **Otro:** WebAssembly, C como IR, etc.

Documenta: si existe VTable, cómo se representan los objetos en memoria (layout del struct LLVM), cómo se produce el binario final (linking).

### 1.7 Runtime
- ¿Existe un runtime en C u otro lenguaje?
- ¿Qué funciones expone? (alloc, print, concat, math, cast error)
- ¿Cómo se enlaza? (compilado y linkeado desde el compilador, o incluido en el Makefile)

### 1.8 Gestión de memoria de objetos en runtime
- ¿Cómo se asigna memoria para objetos HULK en el programa generado?
- ¿Hay GC? Si sí, ¿qué tipo?
- ¿O es memoria que no se libera (leak intencional)?

### 1.9 Features implementados (evidencia en código)
Para cada feature, indica si existe soporte en AST, semántica Y codegen:

| Feature | AST | Semántica | Codegen |
|---------|-----|-----------|---------|
| Iterables / `for` | ¿nodo ForExpr? | ¿type check? | ¿genera IR? |
| Arrays | ¿nodo NewArray? | ¿chequea índice/size? | ¿genera IR? |
| Protocolos | ¿chequeo estructural? | ¿conformidad? | — |
| Functores/lambdas | ¿nodo lambda? | ¿tipo función? | ¿genera IR? |
| Macros | ¿nodo Define? | ¿expansión? | — |
| `case` expression | ¿nodo CaseExpr? | ¿type dispatch? | ¿genera IR? |

---

## Bloque 2 — Lexer

Verifica en el código:

1. ¿Se reconocen todos los operadores de HULK? Checkea: `:=`, `@`, `@@`, `=>`, `->`, `is`, `as`.
2. ¿Identificadores: `[a-zA-Z][a-zA-Z0-9_]*`?
3. ¿Números: soportan decimales `[0-9]+(\.[0-9]+)?`?
4. ¿Strings: soportan escape sequences?
5. ¿Comentarios de línea `#` ignorados?
6. ¿Posición (línea, columna) reportada en tokens?

Para cada punto: cita el archivo y línea donde se define o donde falta.

---

## Bloque 3 — Parser

Verifica en el código:

1. **Niveles de precedencia:** cuenta los niveles reales (busca comentarios `Level N` o la estructura de la gramática). Anota el número exacto.
2. **Asociatividad:** ¿`^` right-assoc? ¿`:=` right-assoc? ¿`+/-` left-assoc?
3. **Dangling-else:** ¿cómo se resuelve en la gramática?
4. **Expresiones-valor:** `let`, `if`, `while`, `for` ¿son expresiones que devuelven valor?
5. **Bloques `{...}`:** ¿el valor es la última expresión?
6. **Recuperación de errores:** ¿intenta continuar tras un error?

Cita archivo y línea para cada hallazgo.

---

## Bloque 4 — Análisis Semántico

### 4.1 Tabla de símbolos
Cita el archivo donde se define. Describe los campos de la estructura.

### 4.2 Referencias cruzadas
¿Existe una pasada de colección de declaraciones? ¿En qué archivo? ¿Qué registra?

### 4.3 Scope y variables
- ¿Verifica variables declaradas antes de usar?
- ¿Verifica `self` solo dentro de métodos?
- ¿Genera warnings de variables no usadas? (cita el archivo y función)

### 4.4 Aridad
¿Verifica número de argumentos en llamadas a funciones, métodos, constructores?

### 4.5 Inferencia de tipos
- ¿Existe pasada de inferencia? ¿Para qué símbolos?
- ¿Cómo funciona? (restricciones por uso, evaluación directa, unificación)
- ¿Calcula LCA para ramas de `if`/`case`? (cita función)

### 4.6 Verificación de tipos
- ¿Verifica operandos aritméticos (Number)?
- ¿Verifica condiciones boolean?
- ¿Verifica compatibilidad en asignaciones?
- ¿Verifica retorno de funciones?
- ¿Maneja subtipado (subclase como supertipo)?

### 4.7 OOP semántico
- ¿Verifica que padre exista?
- ¿Detecta ciclos en herencia? (cita algoritmo y archivo)
- ¿Verifica firma en overrides?

### 4.8 Múltiples errores semánticos
¿El compilador puede reportar varios errores semánticos en una sola ejecución? ¿Cómo?

---

## Bloque 5 — Generación de Código

### 5.1 Tipos primitivos en LLVM
- Number: ¿`double` (f64) o entero?
- Boolean: ¿`i1` o `i8`?
- String: ¿puntero C-style, struct con longitud?

### 5.2 Expresiones
- Aritmética: ¿`fadd`/`fmul` o `add`/`mul`? Cita archivo y línea.
- Comparaciones: ¿`fcmp` o `icmp`?
- Concatenación de strings: ¿llama a función del runtime?
- **Operadores lógicos `&` y `|`**: ¿short-circuit (bloques básicos + `br`) o eager (`build_and`/`build_or`)? Cita exactamente las líneas.

### 5.3 Control de flujo
- `if`: ¿genera bloques `then`/`else`/`merge` con `phi`?
- `while`: ¿bloques `cond`/`body`/`end`?
- `for`: ¿delega a iterable o hardcodea `Range`?

### 5.4 OOP y VTable
- ¿Existe VTable? Cita archivo y función donde se construye.
- ¿Layout del struct: slot 0 = vtable ptr, slot 1 = type_id, slot 2+ = atributos? Cita líneas.
- ¿El type_id se usa para `is`/`as`? ¿Cómo?
- ¿El override reemplaza la entrada de la VTable del padre?
- ¿El constructor inicializa vtable y type_id?

### 5.5 Linking
¿Cómo se produce el binario? (cita la función o líneas donde se llama al linker)

---

## Bloque 6 — Features Opcionales

Para cada feature marcada [x] en el issue:

1. Verifica soporte en AST (cita archivo del nodo).
2. Verifica soporte semántico (cita pasada que lo valida).
3. Verifica soporte en codegen (cita función de generación).
4. Cruza con resultados de tests de esa categoría.

Si el issue marca [x] pero los tests fallan o el codegen está ausente, documéntalo.

---

## Bloque 7 — Exactitud del Reporte

### 7.1 Afirmaciones verificadas
Lista las afirmaciones del reporte que el código confirma. Para cada una, cita el archivo y línea donde se verifica.

### 7.2 Afirmaciones no sustentadas o incorrectas
Para cada afirmación del reporte que el código contradice:
- Cita textualmente la frase del reporte.
- Muestra la evidencia del código (archivo:línea) que la contradice.
- Clasifica: **sobreestimación** / **descripción incorrecta** / **no verificable**.

### 7.3 Omisiones del reporte
Lo que el código hace y el reporte no menciona.

### 7.4 Inconsistencias issue vs. código
Features marcadas [x] que los tests muestran como no funcionales.

---

## Bloque 8 — Diagnóstico de Fallas de Tests

Para cada test que falla, categoriza la causa:

| Categoría | Descripción | Señal |
|-----------|-------------|-------|
| Lexical/Syntactic | El parser rechaza sintaxis válida de HULK | exit 2 |
| Semantic | Error de tipos en código correcto | exit 3 |
| Codegen crash | IR falla al generarse | exit 101 / panic |
| Runtime error | Binario generado produce output incorrecto | output ≠ expected |

Para crashes de codegen (exit 101), intenta identificar el patrón:
- ¿Solo con herencia multinivel?
- ¿Solo con override de métodos?
- ¿Con ciertos tipos primitivos (String)?
- ¿Con despacho dinámico (vtable)?

---

## Formato del Comentario Resumen (OUTPUT 2)

**Longitud: 1000–2000 palabras. Sin referencias a líneas de código. En español.**

```markdown
## 🔍 Evaluación Automática — Claude Code

> Repositorio: <URL> | Rama: <branch> | Tests: <fecha último CI>

### Arquitectura del Compilador

[2–3 párrafos: lenguaje/herramientas, pipeline completo lexer→parser→AST→semántica→codegen,
backend LLVM o VM, runtime, gestión de memoria. Code-first: describe lo que el código hace,
no lo que dice el reporte.]

### Resultados de Tests

| Categoría | Pasados | Total | Estado |
|-----------|---------|-------|--------|
| ok/minimal | N | N | ✅/⚠️ |
...

### Lo que el Compilador Implementa

[Párrafo o lista de lo que efectivamente funciona según código + tests combinados.
Menciona específicamente qué features opcionales están completamente implementados.]

### Discrepancias entre Reporte y Código

**El reporte afirma pero el código no sustenta:**
- [afirmación] → [lo que el código muestra en realidad]

**El código implementa pero el reporte omite:**
- [lista]

### Features Opcionales

| Feature | AST | Semántica | Codegen | Tests |
|---------|-----|-----------|---------|-------|
| Iterables | ✅ | ✅ | ✅ | N/M |
...

### Diagnóstico de Fallas Principales

[2–3 párrafos explicando las causas técnicas de los tests que fallan,
sin referencias a líneas de código pero sí a módulos o componentes.]

### Conclusión

[1–2 párrafos: fortalezas reales verificadas en el código, debilidades críticas
(especialmente en las categorías de tests obligatorios que fallan), y un juicio
sobre la brecha entre lo que el reporte describe y lo que el código ejecuta.]
```

---

## Notas finales para el agente

- Lee el código antes que el reporte.
- Cada hallazgo técnico en el Reporte Detallado (OUTPUT 1) debe tener `archivo.rs:L123`.
- El Comentario Resumen (OUTPUT 2) no lleva referencias a líneas; es para leer en GitHub.
- El reporte detallado no tiene límite de longitud; el comentario sí (máx. 2000 palabras).
- Si hay duda entre lo que el código hace y lo que el reporte dice, el código gana.
- Distingue entre: feature ausente en el código vs. feature en AST/semántica pero con codegen roto.
- Sé justo: reconoce lo que sí funciona.
