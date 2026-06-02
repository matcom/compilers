<p align="center">
<img src="/docs/logo.png" alt="Compilers"></a>

</p>

# ¡Compilers! 🌟

Este es el repositorio central de la asignatura de compilación para 3er año de Ciencias de la Computación de la facultad de MATCOM de la Universidad de La Habana. Aquí se pueden encontrar las especificaciones del proyecto final de la asignatura, la definición del lenguaje a compilar, y otras cosas en progreso.

---

## 📬 Envío del Proyecto

> **Para entregar tu compilador, abre un issue con el template oficial:**
>
> ### [→ Crear submission](https://github.com/matcom/compilers/issues/new?template=grading.yml)

**¿Cómo funciona?**
1. Haz clic en el link de arriba y rellena el template (URL de tu repo, rama, integrantes).
2. El CI clona tu repositorio, ejecuta `make build`, y corre la suite de tests automáticamente.
3. Recibirás un comentario con los resultados en minutos.
4. Si algo falla, corrige y comenta `/regrade` para volver a evaluar.
5. Cuando todos los tests requeridos estén en verde y tu `REPORT.md` tenga al menos 2000 palabras, el profesor revisará tu entrega.

**Antes de enviar**, lee los requisitos técnicos completos: [docs/interface.md](docs/interface.md).  
Incluye un `REPORT.md` en la raíz de tu repo describiendo tu compilador (mínimo 2000 palabras).

---

### 📜 [Evaluación de la asignatura](/docs/eval.md)

Aquí se especifica el sistema de evaluación de la asignatura y la orden del proyecto final.

### 🦸 [Definición del Lenguaje HULK](https://matcom.in/hulk/guide/intro.html)

Descubre **HULK** (**H**avana **U**niversity **L**anguage for **K**ompilers), un lenguaje de programación **didáctico, seguro en tipos, orientado a objetos e incremental**, con herencia simple, polimorfismo y encapsulación a nivel de clase. Además, en HULK es posible definir **funciones globales fuera del alcance de todas las clases**, así como una **única expresión global** que constituye el punto de entrada al programa.

La mayoría de las construcciones sintácticas en HULK son **expresiones**, incluyendo instrucciones condicionales y ciclos. HULK es un lenguaje **estáticamente tipado** con inferencia de tipos opcional, lo que significa que algunas (o todas) las partes de un programa pueden ser anotadas con tipos, y el compilador verificará la consistencia de todas las operaciones.
