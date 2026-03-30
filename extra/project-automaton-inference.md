# Inferencia de Lenguajes Regulares

El objetivo de este proyecto es diseñar un programa capaz de "adivinar" un lenguaje a partir de una secuencia de ejemplos de cadenas **positivas** (cadenas que pertencen al lenguaje) y **negativas** (cadenas que no pertenecen) al lenguaje, que llamaremos por convenio *Alice*.

*Alice* interactúa con un adversario (*Bob*) que ha decidido de antemano construir un **lenguaje regular**. *Alice* tiene permitido realizar una serie $N$ de preguntas del estilo $w_i \in L$, es decir, saber si una cadena arbitraria que *Alice* desee conocer pertenece o no al lenguaje que *Bob* ha construido. *Bob* está obligado a responder de forma correcta en todos los casos. Tras las $N$ preguntas, el turno cambia, y *Bob* preguntará entonces $N$ veces sobre otro conjunto (no necesariamente disjunto) de cadenas y evaluará a qué proporción de las cadenas *Alice* responde de forma correcta. El objetivo de *Alice* será entonces maximizar la cantidad de respuestas correctas a las preguntas de *Bob*, para ello, deberá intentar adivinar el lenguaje que *Bob* ha pensado, o al menos, aproximarse lo más posible.

Formalmente, el programa (*Alice*) que usted debe diseñar funcionará del siguiente modo:

- Al comenzar, lee de la entrada estándar un número $N > 0$, que corresponde a la cantidad de preguntas a realizar.
- Posteriormente, lee de la entrada estándar una línea de símbolos $a_1, a_2, \ldots, a_n$, separados por espacio (e.j. `a b c`) que corresponde al vocabulario del lenguaje a adivinar.
- Luego, realizará exactamente $N$ veces la siguiente operación:
    - Genera una cadena $w_i \in \{a_1, \ldots, a_n\}^*$.
    - Imprime la cadena $w_i$ en la salida estándar.
    - Lee de la entrada estándar una línea, que será `yes` si la cadena $w_i \in L$, `no` en caso contrario.
- Al culminar las $N$ preguntas y respuestas, realizará $N$ veces la siguiente iteración:
    - Lee de la entrada estándar una cadena $w_j \in \{a_1, \ldots, a_n\}^*$.
    - Escribe `yes` o `no` respectivamente si la cadena $w_j$ debe pertenecer al lenguaje $L$ (por supuesto, cometerá errores).

Por ejemplo, supongamos que el lenguaje a reconocer es las cadenas sobre $\{a,b\}$ que tienen 2 $a$ consecutivas, y para ello hay 4 preguntas. El siguiente es un ejemplo de una posible interacción entre *Alice* (su programa) y *Bob* (el programa adversario):

    Bob:   4
    Bob:   a b
    Alice: aa
    Bob:   yes
    Alice: ab
    Bob:   no
    Alice: aba
    Bob:   yes
    Alice: bab
    Bob:   no

Al terminar esta secuencia, supongamos que *Alice* ha inferido que el lenguaje es cadenas que terminan en $a$ (un lenguaje incorrecto pero que tiene una intersección no vacía con el lenguaje de *Bob*). Luego comienza la fase de evaluación.

    Bob:   aabb
    Alice: no
    Bob:   bbaa
    Alice: yes
    Bob:   abbb
    Alice: no
    Bob:   bbba
    Alice: yes

Por lo tanto, *Alice* ha obtenido un $50\%$ de las respuestas correctas.
