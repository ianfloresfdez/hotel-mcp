# hotel-mcp

Un sistema de reservas de hotel muy sencillo con dos formas de usarlo:

- **Una web de recepción** para el personal del hotel.
- **Un servidor MCP** para que un asistente de IA (Claude Desktop, Claude Code, Cursor…) pueda consultar disponibilidad, hacer reservas y cancelarlas hablando con él.

Los dos usan la misma base de datos, así que si le pides a Claude que reserve una habitación, la reserva aparece en la web a los pocos segundos (en morado).

Lo hice para practicar MCP con el SDK oficial de Python, y lo he dejado pequeño a propósito.

## Qué es MCP, en una frase

MCP (Model Context Protocol) es un estándar para conectar asistentes de IA con sistemas externos. Tú escribes un "servidor MCP" que expone unas funciones, y cualquier asistente compatible puede usarlas sin integraciones a medida.

## Cómo funciona

```
   Claude (Desktop / Code)              Navegador
          │                                 │
          │ MCP                             │ HTTP
          ▼                                 ▼
   hotel/mcp_server.py               hotel/web.py + static/index.html
   (lo que puede hacer la IA)        (la web de recepción)
          └────────────────┬────────────────┘
                           ▼
                     hotel/core.py   ← las reglas del hotel
                           ▼
                        hotel.db     ← base de datos SQLite
```

1. **`core.py`** contiene toda la lógica: qué habitaciones están libres, cuánto cuesta una estancia, cómo se reserva, cómo se cancela y cuánto se devuelve. Guarda los datos en SQLite. La primera vez crea la base de datos con 6 habitaciones y unas reservas de ejemplo.
2. **`mcp_server.py`** es el servidor MCP. Son unas pocas funciones que llaman a `core.py`. Cada función lleva el decorador `@mcp.tool()`, y con eso el SDK ya las publica para que Claude las vea y las use.
3. **`web.py`** es la web de recepción, hecha con FastAPI. También llama a `core.py`.

Como el MCP y la web usan la misma lógica y la misma base de datos, siempre están sincronizados.

## Qué puede hacer la IA

| Tipo | Nombre | Qué hace |
|---|---|---|
| tool | `check_availability` | Habitaciones libres para unas fechas y número de personas, con el precio. También dice qué día es hoy |
| tool | `get_booking` | Muestra una reserva a partir de su localizador (por ejemplo ABC123) |
| tool | `occupancy_report` | Quién está alojado, quién llega y quién se va un día concreto |
| tool | `create_booking` | Hace una reserva (pide confirmación antes) |
| tool | `cancel_booking` | Cancela una reserva (pide confirmación antes) |
| resource | `hotel://policies` | Las normas de cancelación del hotel |
| prompt | `front_desk_briefing` | Plantilla para pedir el resumen del día en recepción |

- Las **tools** son acciones que la IA decide usar.
- Los **resources** son información que se puede leer.
- Los **prompts** son plantillas que elige el usuario.

## Ejemplo de conversación

```
Tú:      ¿Hay una doble libre el fin de semana que viene?
Claude:  (usa check_availability)
         Sí, la 202, de viernes a domingo, 220 €. ¿La reservo?
Tú:      Sí, a nombre de Eva Ruiz, eva@example.com.
Claude:  (usa create_booking sin confirmar → le devuelve la pregunta con el precio)
         (usa create_booking con confirm=true)
         Hecho: localizador K7Q2MZ, habitación 202, 220 €.
```
<sub>Ejemplo orientativo: las palabras exactas dependen del asistente.</sub>

## Decisiones sencillas pero importantes

- **Quien confirma es el usuario, no la IA.** Reservar y cancelar se hace en dos pasos. La primera llamada solo devuelve la pregunta con el precio o el reembolso. La reserva o cancelación solo se ejecuta si la IA vuelve a llamar con `confirm=true`, y la descripción de la tool le indica que lo haga únicamente cuando el usuario diga que sí.
- **No se puede reservar dos veces la misma habitación.** La comprobación de disponibilidad y la reserva van dentro de una misma transacción, así que aunque la web y la IA reserven a la vez, solo una lo consigue.
- **Errores claros.** Si algo no se puede hacer, el mensaje explica qué pasa y qué hacer ("La habitación 102 no está libre… usa check_availability"). La IA lo lee y se corrige sola.
- **La IA sabe qué día es.** Un modelo no sabe la fecha de hoy, así que `check_availability` se la devuelve. Así entiende bien "el fin de semana que viene".

## Cómo arrancarlo

Necesitas Python 3.10 o superior.

```bash
git clone https://github.com/ianfloresfdez/hotel-mcp
cd hotel-mcp
python -m venv .venv
.venv\Scripts\activate          # en Windows  (en macOS/Linux: source .venv/bin/activate)
pip install -e ".[dev]"
```

**Web de recepción:** ejecuta `hotel-web` y abre http://127.0.0.1:8850

**Conectarlo a Claude Desktop:** en Claude Desktop ve a *Settings → Developer → Edit Config*, añade esto y reinicia Claude:

```json
{
  "mcpServers": {
    "hotel": {
      "command": "C:/ruta/a/hotel-mcp/.venv/Scripts/hotel-mcp.exe"
    }
  }
}
```

En macOS/Linux la ruta es `/ruta/a/hotel-mcp/.venv/bin/hotel-mcp`.

No hace falta arrancar el servidor MCP a mano: Claude lo lanza solo cuando lo necesita.

**Conectarlo a Claude Code:**

```bash
claude mcp add hotel -- C:/ruta/a/hotel-mcp/.venv/Scripts/hotel-mcp.exe
```

**Probarlo sin Claude** (con el MCP Inspector, una herramienta oficial para llamar a cada tool a mano):

```bash
npx @modelcontextprotocol/inspector .venv/Scripts/hotel-mcp.exe
```

Consejo: deja la web abierta mientras hablas con Claude y verás aparecer sus reservas.

## Tests

```bash
pytest
```

Hay 19 tests. Unos prueban las reglas del hotel (solapamiento de fechas, capacidad, cancelaciones…). Otros hablan con el servidor MCP como lo haría Claude.

## Qué añadiría para usarlo de verdad

Es un proyecto de práctica. Para producción añadiría:

- **Confirmación con elicitation:** que el propio cliente muestre un botón de "Confirmar", en vez de depender de que la IA pregunte.
- **Autenticación (OAuth 2.1)** si se usa en remoto, y que cada cliente solo pueda ver sus propias reservas.
- **Tratar con cuidado el texto que escriben los huéspedes** (por ejemplo, las peticiones especiales), porque podría contener instrucciones dirigidas a la IA (*prompt injection*).
- Una base de datos como PostgreSQL, límites de uso y registro de cada acción de la IA.

## Licencia

MIT
