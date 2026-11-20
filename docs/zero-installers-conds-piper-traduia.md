# Comportamiento de los instaladores zero-center: Piper TTS y TraduIA

## 1. Reglas generales

- **TraduIA no necesita Piper para instalarse.** Piper es opcional.
- **Piper es independiente de TraduIA.** Se puede instalar y desinstalar por separado.
- En el **instalador de Piper**, el servidor se instala siempre; las voces son opcionales.
- En el **instalador de TraduIA**, si se marca Piper y no está instalado, se instalan **todas las voces**.
- Si Piper ya está instalado, TraduIA **no añade ni modifica voces**.
- Las voces pueden quedar instaladas sin el servidor, pero no se usan hasta reinstalarlo.

### 1.1 Dependencias y estado

- `zero-lliurex-traduia` usa `Recommends: zero-lliurex-piper-tts-server`.
  La app Piper se instala por defecto desde consola, pero no es obligatoria.
- `traduia` usa `Suggests: piper-tts-server`. `apt-get install traduia` no
  instala Piper; `apt-get install traduia piper-tts-server` sí.
- `piper-tts-server` usa `Recommends` para las voces.
- La app Piper tiene `Service=False`: no usa estado N4D ni `set-configured`.
  Zero-center muestra el estado del epi/paquete, sin overlay.
- TraduIA mantiene su estado vía `traduia-config`; el `.app` sigue con
  `Service` comentado.
- Una instalación manual/offline no actualiza el estado N4D. TraduIA queda
  sin configurar hasta `traduia-config install/postinstall` o hasta usar el
  instalador de zero-center. Piper no deja estado pendiente.

## 2. Instalador de Piper

### 2.1 Opciones

- **Servidor Piper**: marcado por defecto.
- **Voces**: desmarcadas por defecto.

### 2.2 Instalación

| Situación inicial | Qué marco | Resultado |
|---|---|---|
| Nada instalado | Solo servidor | Se instala el servidor, sin voces |
| Nada instalado | Servidor + algunas voces | Servidor + solo esas voces |
| Nada instalado | Servidor + todas las voces | Servidor + las 8 voces |
| Servidor ya instalado | Algunas voces nuevas | Se añaden solo las voces marcadas que falten |
| Servidor + algunas voces | Más voces | Se añaden las nuevas; las existentes se mantienen |
| Servidor + todas las voces | Nada nuevo | No cambia nada |
| Servidor desmarcado | Voces | El servidor se instala igualmente; el servidor es obligatorio |

No se puede instalar solo voces desde este instalador: el servidor se instala siempre.

### 2.3 Desinstalación

| Qué marco | Resultado |
|---|---|
| Solo voces | Se eliminan esas voces; el servidor permanece |
| Servidor + voces | Se elimina el servidor y las voces marcadas; además se pregunta si se eliminan **todas** las voces instaladas |
| Solo servidor | Se elimina el servidor y se pregunta si se eliminan también todas las voces |
| Servidor desmarcado, voces marcadas | Se eliminan las voces; el servidor permanece |

En el aviso de eliminación de voces:

- **Sí** → se eliminan todas las voces instaladas.
- **No** → las voces permanecen en disco, aunque no funcionarán hasta reinstalar el servidor.

## 3. Instalador de TraduIA

### 3.1 Opciones

- **TraduIA**: marcado por defecto.
- **Piper TTS**: desmarcado por defecto.

### 3.2 Instalación

| Situación inicial | Qué marco | Resultado |
|---|---|---|
| Nada instalado | Solo TraduIA | Se instala TraduIA; Piper no se toca |
| Nada instalado | TraduIA + Piper | Se instala y configura TraduIA, y después Piper con **todas** las voces |
| Nada instalado | Solo Piper | Se instala Piper con todas las voces; TraduIA no se instala |
| TraduIA instalado, Piper no | Solo TraduIA | Se reinstala/actualiza TraduIA; Piper sigue sin instalarse |
| TraduIA instalado, Piper no | TraduIA + Piper | Se actualiza TraduIA y se instala Piper con todas las voces |
| TraduIA instalado, Piper no | Solo Piper | Se instala Piper con todas las voces; TraduIA permanece |
| Piper instalado con algunas voces, TraduIA no | Solo TraduIA | Se instala TraduIA; Piper y sus voces no se tocan |
| Piper instalado con algunas voces, TraduIA no | TraduIA + Piper | Se instala TraduIA; Piper no se reinstala y **no se añaden voces** |
| Piper instalado con algunas voces, TraduIA no | Solo Piper | No se añade nada nuevo |
| Ambos instalados | Solo TraduIA | Se actualiza TraduIA; Piper y voces permanecen |
| Ambos instalados | TraduIA + Piper | Se actualiza TraduIA; Piper no se reinstala y no se añaden voces |
| Ambos instalados | Solo Piper | No se añade nada nuevo |

TraduIA **no permite elegir voces**: si instala Piper, instala todas. Para elegir voces concretas hay que usar el instalador de Piper.

### 3.3 Desinstalación

| Qué marco | Resultado |
|---|---|
| Solo TraduIA (por defecto) | Se elimina TraduIA; Piper y sus voces permanecen |
| TraduIA + Piper | Se eliminan TraduIA y Piper; al quitar Piper se pregunta si se eliminan también las voces |
| Solo Piper | Se elimina Piper y se pregunta por las voces; TraduIA permanece |

## 4. Dependencias entre ambos

- **TraduIA sin Piper**: funciona como instalador, pero TraduIA se queda sin motor de voz local hasta que se instale Piper.
- **TraduIA con Piper**: si Piper falta, se instala con todas las voces; si ya existe, se respeta la instalación y las voces que tenga.
- **Piper sin TraduIA**: totalmente funcional; se puede usar para instalar el servidor y las voces que se quieran.
- **Instalación manual de Piper por consola**: instala el servidor y todas las voces.
- **Voces sin servidor**: pueden quedar instaladas, pero no se usan hasta reinstalar Piper.

## 5. Resumen rápido

- Instalador de Piper: servidor obligatorio + voces opcionales.
- Instalador de TraduIA: TraduIA marcado por defecto; Piper opcional.
- Si TraduIA instala Piper, instala todas las voces.
- Si Piper ya existe, TraduIA no añade voces.
- Al eliminar Piper, se puede decidir si se eliminan también las voces.
- Las voces pueden sobrevivir a la desinstalación de Piper, pero no funcionan sin él.

## 6. Instalación offline

El repositorio generado por `traduia-make-repo --full` incluye las listas
`debs-jammy.txt`/`debs-noble.txt` (TraduIA, instaladores zero-center, Piper,
voces, ONNX y dependencias estáticas), el índice apt local
(`Packages`/`Packages.gz`) y el instalador `install-offline.sh`.

```bash
sudo ./install-offline.sh --server   # solo TraduIA
sudo ./install-offline.sh --client   # TraduIA + Piper + voces
sudo ./install-offline.sh --all
sudo ./install-offline.sh --piper
```

- El instalador usa un entorno apt temporal en `/tmp` con los repositorios
  del sistema y el repo local al final.
- No modifica `/etc/apt`, `/var/lib/apt/lists` ni `/var/cache/apt`.
- Solo instala paquetes; después hay que ejecutar `sudo traduia-config install`
  (o usar zero-center).
- Si se instala manualmente/offline, el estado N4D de TraduIA queda sin
  configurar hasta `traduia-config` o el instalador de zero-center. Piper no
  usa estado (`Service=False`).
- Si un paquete Piper no está disponible en el repo, el instalador avisa y
  continúa con el resto; TraduIA no falla por Piper.
- `--debs-dir-jammy <dir>` y `--debs-dir-noble <dir>` permiten aportar
  `.deb` locales que falten para cada distro. Se elige la versión máxima
  disponible entre esas fuentes y lliurex.net/Ubuntu.
- `--extra-repo-jammy <url>` y `--extra-repo-noble <url>` añaden
  repositorios apt extra para paquetes aún no publicados. lliurex.net y
  Ubuntu siguen presentes y gana la versión máxima.
