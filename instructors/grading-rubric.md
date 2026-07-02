# Rúbrica de Evaluación Automática — Proyecto HULK Compiler

> **Instrucciones para el agente evaluador:**
> Esta rúbrica guía la producción de un comentario de evaluación en el issue de GitHub de cada equipo.
> El flujo obligatorio es: **código primero, reporte después**.
> Nunca describas lo que el reporte dice como si fuera hecho; verifica siempre en el código.
> Emite la evaluación en el issue con la etiqueta `## 🔍 Evaluación Automática — Claude Code`.

---

## 0. Preparación

Antes de evaluar, realiza los siguientes pasos:

1. **Clona o actualiza el repositorio** del estudiante (rama indicada en el issue).
2. **Lee el último comentario del bot de CI** para obtener el resumen de tests.
3. **Lee `REPORT.md`** en su totalidad.
4. **Lista todos los archivos fuente** con `find . -name "*.rs" -o -name "*.c" -o -name "*.cpp" | sort` (o el lenguaje correspondiente).
5. **Lee los archivos clave** según las secciones de esta rúbrica.

La evaluación se estructura en **siete bloques**. Emite cada bloque en orden.

---

## Bloque 1 — Descripción Arquitectónica (OBLIGATORIO)

Este bloque debe producir 2–4 párrafos describiendo la arquitectura **tal como existe en el código**, no como la describe el reporte. Responde sistemáticamente cada una de las siguientes preguntas buscando evidencia directa en el código:

### 1.1 Lenguaje de implementación
- ¿En qué lenguaje está escrito el compilador? (Rust, C, C++)
- ¿Usa un sistema de build específico? (Cargo, CMake, Make)
- ¿Depende de bibliotecas externas relevantes? (inkwell, llvm-sys, etc.)

### 1.2 Análisis léxico (Lexer / Tokenizer)
Busca en el código la implementación del lexer:

- **Manual (hand-written):** existe un archivo lexer/tokenizer con bucles de reconocimiento de caracteres, autómata de estados, o tablas de transición.
- **Generador integrado en parser generator:** ej. LALRPOP incluye su propio sistema de tokens vía bloques `match {}` con regex. Verifica si existe un bloque `match` en el archivo `.lalrpop`.
- **Flex/JFlex/re2c:** existe un archivo `.l` o `.flex`.
- **Librería de combinadores:** ej. `logos`, `nom`, `pest`.

Documenta: qué archivo implementa el lexer, cómo se definen los tokens (regex, enum, tabla), cómo se manejan los comentarios, si hay reporte de posición (línea/columna).

### 1.3 Análisis sintáctico (Parser)
Busca cómo se construye el parser:

- **LALRPOP:** existe archivo `.lalrpop` con gramática BNF.
- **Parser combinator:** ej. `nom`, `pest`, `chumsky` — muchas funciones `parse_X()` encadenadas.
- **Recursive descent hand-written:** funciones `parse_expr()`, `parse_stmt()`, etc. escritas manualmente.
- **ANTLR / Bison / Yacc:** archivos `.g4`, `.y`.

Documenta: tipo de parser (LL, LR, PEG, etc.), si tiene recuperación de errores, cómo se reportan errores sintácticos (línea/columna).

### 1.4 AST (Árbol de Sintaxis Abstracta)
Busca las definiciones de nodos del AST:

- **Estructura:** ¿son `enum` con variantes (Rust), `struct` con herencia (C++), clases polimórficas (C)?
- **Mutabilidad:** ¿el AST se modifica en pasadas semánticas (mutable), o se construye y solo se lee (immutable)?
- **Anotación de tipos:** ¿los nodos del AST guardan información de tipo? ¿Se añade en una pasada posterior o se fija durante el parsing?
- **Patrón Visitor:** ¿existe un trait/interfaz `Visitor` o `Visit`? ¿Las pasadas semánticas lo usan?
- **Span / posición:** ¿cada nodo guarda su posición en el fuente para errores?

### 1.5 Análisis semántico
Cuenta y describe las pasadas semánticas:

- ¿Cuántas pasadas distintas existen? (archivos o módulos separados)
- ¿Qué hace cada una? (colectar declaraciones, chequear scopes, inferir tipos, verificar tipos)
- ¿Existe tabla de símbolos? ¿Cómo está estructurada? (HashMap, árbol de scopes, stack)
- ¿Maneja referencias cruzadas? (clases y funciones usables antes de declararse)
- ¿Detecta ciclos de herencia?
- ¿Genera errores múltiples en una sola pasada o para al primer error?

### 1.6 Backend de generación de código
Identifica el backend de codegen:

- **LLVM vía Inkwell (Rust):** imports de `inkwell::`, archivo `codegen/` con `Context`, `Module`, `Builder`.
- **LLVM vía llvm-sys (Rust, bindings C):** llamadas `LLVMBuildXxx`.
- **LLVM vía API C++ directa:** includes `llvm/IR/...`.
- **LLVM vía CLI (llc, clang):** el compilador genera texto `.ll` y llama a `clang`/`llc` como proceso externo.
- **Máquina virtual propia:** existe código de un intérprete de bytecode, instrucciones custom, stack VM.
- **Otro backend:** WebAssembly, C como IR, etc.

Documenta: ¿se generan structs/tipos LLVM propios? ¿Existe VTable? ¿Cómo se representan los objetos en memoria (layout del struct en LLVM)?

### 1.7 Runtime
- ¿Existe un runtime en C u otro lenguaje que se enlaza con el binario generado?
- ¿Qué funciones provee? (malloc/alloc, print, strings, math)
- ¿Cómo se hace el enlazado? (llamada a `cc`/`clang` desde el compilador, Makefile)

### 1.8 Gestión de memoria de los objetos generados
- ¿Cómo se asigna memoria para objetos HULK en el programa generado? (`malloc`, `calloc`, GC, arena allocator)
- ¿Hay recolección de basura? Si sí, ¿qué tipo? (mark-and-sweep, reference counting, Boehm GC)
- ¿O es memoria no liberada (leak intencional para simplificar)?

### 1.9 Features adicionales implementados
Busca en el código evidencia de:

- **Iterables / `for` loops:** nodo `ForExpr` en AST, clase `Range` o interfaz iterable en codegen.
- **Vectores / Arrays:** nodo `NewArray`, acceso por índice `[]`, método `.size()`.
- **Protocolos / Interfaces:** chequeo estructural de conformidad, nodo `Interface` en AST o symbol table.
- **Functores / lambdas:** nodo de función anónima, closure capture en el AST.
- **Macros:** expansión en tiempo de compilación, nodo `MacroDef` o `Define`.
- **`case` expression:** nodo `CaseExpr`, despacho por tipo dinámico.
- **Operador `with`:** null-safety.

Para cada uno: indica si existe soporte en el AST, en semántica, y en codegen.

---

## Bloque 2 — Evaluación del Lexer

**En el código, busca y verifica:**

1. ¿Cómo se definen los tokens? Lista los tokens reconocidos (keywords, operadores, literales).
2. ¿Se reconocen todos los operadores de HULK? Checkea: `:=`, `@`, `@@`, `=>`, `->`, `is`, `as`, `**` si aplica.
3. ¿Los identificadores siguen la regla `[a-zA-Z][a-zA-Z0-9_]*`?
4. ¿Los números soportan decimales (`[0-9]+(\.[0-9]+)?`)?
5. ¿Los strings soportan escape sequences (`\"`, `\\`, `\n`)?
6. ¿Se ignoran comentarios de línea (`#`)?
7. ¿Existe reporte de posición (línea, columna)?

**Contrasta con el reporte:** ¿el reporte describe correctamente el lexer implementado?

**Señales de alerta:**
- El reporte describe un autómata o estados del lexer que no aparecen en el código.
- Los tokens no incluyen todos los operadores del lenguaje.
- No hay manejo de posición para errores.

---

## Bloque 3 — Evaluación del Parser

**En el código, busca y verifica:**

1. **Niveles de precedencia:** cuenta los niveles reales en la gramática (no los que dice el reporte).
2. **Asociatividad:** verifica que `^` sea right-associative, `:=` sea right-associative, los aritméticos left-associative.
3. **Dangling-else:** ¿está resuelto? Busca en la gramática cómo se maneja `if-elif-else`.
4. **Expresiones que producen valor:** `let`, `if`, `while`, `for` deben ser expresiones, no statements.
5. **Bloques `{...}`:** ¿se parsean como listas de expresiones separadas por `;`? ¿El valor del bloque es la última expresión?
6. **`new ClassName(args)`:** ¿existe en la gramática?
7. **Acceso a miembros:** `obj.attr`, `obj.method(args)`.
8. **Indexación:** `arr[i]`.
9. **Recovery de errores:** ¿el parser intenta recuperarse y reportar múltiples errores, o para al primero?

**Contrasta con el reporte:** ¿los niveles de precedencia mencionados coinciden con los del código?

---

## Bloque 4 — Evaluación Semántica

**En el código, busca y verifica cada uno:**

### 4.1 Tabla de símbolos
- ¿Existe una estructura centralizada? Describe sus campos.
- ¿Maneja scopes anidados? ¿Cómo? (stack de HashMaps, árbol de scope, etc.)

### 4.2 Resolución de referencias cruzadas
- ¿Las funciones y clases pueden referenciarse antes de declararse?
- ¿Existe una pasada de "colección de declaraciones" separada del chequeo?

### 4.3 Chequeo de scope
- ¿Se verifica que variables usadas estén declaradas?
- ¿Se reporta error cuando `self` se usa fuera de un método?
- ¿Se reportan variables declaradas pero no usadas? (warning)

### 4.4 Chequeo de aridad
- ¿Se verifica que las llamadas a funciones/métodos/constructores tengan el número correcto de argumentos?

### 4.5 Inferencia de tipos
- ¿Existe inferencia? ¿Para qué símbolos? (parámetros de funciones, atributos de clase, variables `let`)
- ¿Cómo se implementa? (restricciones por uso, evaluación directa del inicializador, unificación)
- ¿Se calcula LCA (Lowest Common Ancestor) para ramas de `if`/`while`?

### 4.6 Verificación de tipos
- ¿Se verifican operandos de operadores aritméticos (deben ser Number)?
- ¿Se verifican condiciones de `if`/`while` (deben ser Boolean)?
- ¿Se verifica compatibilidad en asignaciones `:=`?
- ¿Se verifica el tipo de retorno de funciones?
- ¿Se manejan tipos de subclase como supertipo (subtipado estructural)?

### 4.7 Herencia y OOP
- ¿Se verifica que la clase padre exista?
- ¿Se detectan ciclos de herencia?
- ¿Se verifica que el método override tenga la misma firma que el método padre?
- ¿Se valida el uso correcto de `base(args)` en constructores?

### 4.8 Cantidad de errores reportados
- ¿El compilador reporta un solo error semántico o múltiples en la misma ejecución?
- Esto es **requisito obligatorio** según la especificación.

---

## Bloque 5 — Evaluación del Generador de Código

**En el código, busca y verifica:**

### 5.1 Representación de tipos primitivos en LLVM
- Number: ¿`double` (f64) o `i64`?
- Boolean: ¿`i1` o `i8`?
- String: ¿puntero a `i8*` (C-style), struct con longitud, etc.?

### 5.2 Expresiones
- ¿Aritmética genera instrucciones float o int (`fadd`/`add`)?
- ¿Comparaciones generan `fcmp`/`icmp` correctamente?
- ¿Concatenación de strings llama a función del runtime?
- ¿Operadores lógicos `&` y `|` implementan cortocircuito (bloques básicos LLVM con `br` condicional) o evaluación eager (`build_and`/`build_or`)?

### 5.3 Control de flujo
- ¿`if-elif-else` genera bloques básicos separados con `br` y nodos `phi`?
- ¿`while` genera bloques `cond`, `body`, `end` con saltos condicionales?
- ¿`for` delega a un iterable o hardcodea `Range`?

### 5.4 Funciones
- ¿Las funciones HULK se emiten como funciones LLVM?
- ¿Las llamadas generan instrucciones `call`?
- ¿Se manejan llamadas recursivas?

### 5.5 OOP y VTable
- ¿Cada clase HULK se traduce a un `StructType` LLVM?
- ¿El layout del struct incluye: slot 0 = vtable ptr, slot 1 = type_id, slot 2+ = atributos?
- ¿Existe una VTable global constante por clase con punteros a función?
- ¿El despacho dinámico carga el puntero de la VTable en runtime?
- ¿Los constructores asignan memoria vía el runtime?
- ¿La herencia copa el layout del padre y agrega atributos propios al final?
- ¿`is` compara `type_id`? ¿`as` verifica y castea o falla gracefully?

### 5.6 Linking
- ¿Cómo se produce el binario final? (llamada a `cc`/`clang`/`ld`, flags `-lm`, etc.)

---

## Bloque 6 — Features Opcionales

Para cada feature, verifica en el código:

| Feature | Qué buscar en el código | Puntaje |
|---------|------------------------|---------|
| **Iterables / `for`** | Nodo `ForExpr`, clase `Range` con `next()`/`current()`, codegen de `for` | Extra |
| **Arrays / Vectors** | Nodo `NewArray`, indexación `[]`, método `.size()`, generación de arrays LLVM | Extra |
| **Protocolos** | Chequeo estructural de métodos, conformidad sin herencia explícita | Extra |
| **Functores** | Nodo de función anónima o lambda, tipo `(T)->R`, llamada como valor | Extra |
| **Macros** | Expansión en tiempo de compilación, nodo `Define`, sustitución de parámetros | Extra |

Para cada feature marcada como implementada en el issue:
1. Verifica que existe soporte en el **AST** (nodo correspondiente).
2. Verifica que existe soporte en el **análisis semántico** (type checking).
3. Verifica que existe soporte en el **codegen** (emisión de IR).
4. Cruza con los **tests** de esa categoría.

Si el issue marca [x] pero los tests fallan o el soporte en codegen está incompleto, documéntalo explícitamente.

---

## Bloque 7 — Exactitud del Reporte

Después de haber analizado el código, evalúa el reporte comparando cada afirmación técnica:

### 7.1 Afirmaciones verificadas
Lista las afirmaciones del reporte que el código **confirma**. Ej:
- "VTable con slot 0 = vtable ptr, slot 1 = type_id" → verificado en `classes.rs`.

### 7.2 Afirmaciones no sustentadas o incorrectas
Lista las afirmaciones del reporte que el código **contradice o no puede verificar**. Para cada una:
- Cita textualmente la afirmación del reporte.
- Muestra la evidencia del código que la contradice.
- Clasifícala: **sobreestimación** (dice que hay algo que no existe), **descripción incorrecta** (existe pero funciona diferente), o **omisión inversa** (el código tiene algo que el reporte ignora).

### 7.3 Omisiones del reporte
Lista funcionalidades o detalles que el código implementa y que el reporte **no menciona**.

### 7.4 Inconsistencias entre issue y código
- ¿El issue marca [x] en features que los tests muestran como no funcionales?
- ¿Los crashes de codegen (exit 101) sugieren infraestructura parcialmente implementada?

---

## Bloque 8 — Diagnóstico de Fallas de Tests

Para cada test que falla, intenta categorizar la causa:

| Categoría | Descripción | Indicador |
|-----------|-------------|-----------|
| **Lexical/Syntactic** | El parser rechaza sintaxis válida | exit 2, "SYNTACTIC: Token inesperado" |
| **Semantic** | Error de tipos o scope en código válido | exit 3 |
| **Codegen crash** | El IR falla al generarse | exit 101 o similar (no 0/1/2/3) |
| **Runtime error** | El binario generado tiene comportamiento incorrecto | output ≠ expected |
| **Linking error** | El binario no se puede producir | error de linker |

Para los crashes de codegen (los más frecuentes en proyectos con OOP), intenta identificar el patrón:
- ¿Falla solo con herencia múltiple/multinivel?
- ¿Falla cuando hay override de métodos?
- ¿Falla con ciertos tipos (String vs Number)?
- ¿Falla en llamadas a métodos virtuales (despacho dinámico)?

---

## Formato del Comentario Final

El comentario en GitHub debe seguir esta estructura exacta:

```markdown
## 🔍 Evaluación Automática — Claude Code

> **Repositorio:** <URL>
> **Rama:** <branch> | **Último reporte CI:** <fecha>

### 1. Arquitectura del Compilador
[2-4 párrafos según Bloque 1]

### 2. Resumen de Tests
[tabla de resultados]

### 3. Lo que el Código Implementa
[hallazgos verificados, organizados por fase]

### 4. Discrepancias: Reporte vs. Código
#### Lo que el reporte afirma pero el código no sustenta
[lista numerada con citas y evidencia]
#### Lo que el código tiene y el reporte omite
[lista]

### 5. Features Opcionales
[tabla de features marcadas vs. verificadas]

### 6. Diagnóstico de Fallas
[categorización de tests que fallan]

### 7. Conclusión
[2-3 párrafos: fortalezas reales, debilidades críticas, gap reporte vs. código]
```

---

## Criterios de Calidad del Reporte

Al evaluar el `REPORT.md`, considera:

| Criterio | Suficiente | Excelente |
|----------|------------|-----------|
| Longitud | ≥ 2000 palabras | ≥ 3000 palabras con profundidad técnica |
| Arquitectura | Describe cada fase del compilador | Explica decisiones de diseño y alternativas descartadas |
| Exactitud | Las afirmaciones principales coinciden con el código | Todas las afirmaciones técnicas verificables coinciden |
| Limitaciones | Menciona qué no funciona o está incompleto | Explica el diagnóstico de las limitaciones |
| Evidencia | Referencias a archivos o funciones del código | Referencias específicas con nombres de función y módulo |

---

## Notas para el Agente

- **Prioriza el código sobre el reporte.** Si el reporte dice "implementamos X" pero X no está en el código, es una discrepancia, no un hecho.
- **Sé específico.** En lugar de "el codegen tiene problemas", di "el método `gen_method_body` en `classes.rs:492` puede devolver `None` cuando el cuerpo del método contiene llamadas a métodos virtuales sin tipo resuelto."
- **Sé justo.** Reconoce lo que sí funciona. Un 18/20 en tests mínimos es un logro real.
- **Distingue bugs de ausencias.** Un feature que existe en el AST y la semántica pero crashea en codegen es diferente a un feature que no existe en absoluto.
- **Calibra la longitud.** La evaluación debe tener entre 1500 y 3000 palabras. Si supera 4000, prioriza y recorta.
- **Idioma:** Escribe la evaluación en español, siguiendo el idioma del reporte del estudiante.
