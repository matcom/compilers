# 📜 Especificación del Proyecto de Compilación y Sistema de Evaluación

---

## 🛠 **Especificaciones Técnicas del Proyecto**

### 1. **Objetivo Principal**

Desarrollar un compilador para el lenguaje **HULK** ([Definición del Lenguaje](https://matcom.in/hulk/guide/intro.html)) que:

- **Compile** código HULK y permita su **ejecución**.
- Genere **código intermedio LLVM**, el cual podrá ser:
  - Interpretado con herramientas existentes.
  - Compilado a lenguaje máquina.
  - Ejecutado en una máquina virtual.
- **No se aceptan** intérpretes directos (sin generación de código intermedio).

### 2. **Equipos**

Los equipos están formados por tres integrantes. En casos excepcionales y con previa aprobación del colectivo se aceptarán equipo de dos estudiantes.

### 3. **Lenguajes Permitidos**

- **C**, **C++** o **Rust** (a elección del equipo).

### 4. **Requisitos y Features Opcionales**

| **Categoría**          | **Elementos**                                                                                    |
| ---------------------- | ------------------------------------------------------------------------------------------------ |
| **Requisitos Mínimos** | `Expresiones`, `Funciones`, `Variables`, `Condicionales`, `Ciclos`, `Tipos`, `Chequeo de Tipos`. |
| **Features Extra**     | `Protocolos`, `Iterables`, `Vectores`, `Functores`, `Macros` (_sintaxis modificable_).           |

- **Nota sobre Features Extra**:
  - Su implementación (aunque con sintaxis adaptada) puede mejorar la **nota final del proyecto** y, previa coordinación, la nota en _Lenguajes de Programación_.

### 5. **Manejo de Errores**

- **Reportes Obligatorios**:
  - Errores **semánticos**: Informar la **máxima cantidad de errores detectados** en una sola pasada.
  - Errores en _lexer_ y _parser_: Es opcional reportar más de un error, pero se valora la robustez.

---

## 📊 **Sistema de Evaluación de la Asignatura**

### 1. **Componentes de la Asignatura**

La asignatura se divide en tres ejes:

1. **Proyecto de Compilación** (obligatorio).
2. **Conocimiento Teórico del proceso de Compilación**.
3. **Teoría de Lenguajes y Autómatas**.

Para evaluar teoría de lenguajes se realizará una prueba intrasemestral, de no aprobar este contenido deberá evaluarlo en las pruebas finales.

### 2. **Temas Evaluados de Compilación**

Los cuatro temas clave (**deben aprobarse con _Suficiente_ o _Excelente_**):

- **Lexer**
- **Parser**
- **Chequeo Semántico**
- **Generación de Código**

#### **Reglas Clave**:

- Uso de herramientas generadoras (e.g., Flex, Bison):
  - **No eximen** los temas de _Lexer_ y _Parser_ a menos que se implementen los generadores desde cero.
- **Chequeo Semántico y Generación de Código**:
  - Solo se evalúan como _Excelente_ mediante el proyecto.
  - Tienen **mayor peso** que las evaluaciones escritas.

### 3. **Evaluaciones Escritas**

- **3 oportunidades** para aprobar: final, re-evaluación y _"mundial"_.
- **Nota Final por Tema**:
  - Máximo entre:
    - Nota del proyecto.
    - Nota del examen final.
    - Nota de re-evaluación.
    - Nota de _"mundial"_.

## ❓ **[Preguntas Frecuentes (WIP)](/docs/faq.md)**

**⚠️ Importante**:

- Las decisiones de diseño (especialmente en features extra) deben documentarse en el repositorio.
- La coordinación con el colectivo de profesores es esencial para validar mejoras de nota cruzadas entre asignaturas.
- Un compilador es un producto de software que se asume **sin errores**, por tanto, robustez y rigurosidad en su implementación deben ser prioridad.
