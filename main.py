import asyncio
from asyncio import to_thread
from contextlib import asynccontextmanager
from fastapi import FastAPI, WebSocket
from fastapi.responses import HTMLResponse
from starlette.websockets import WebSocketDisconnect


html = """
<!DOCTYPE html>
<html lang="es">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Chat</title>
  <style>
    /* ===== Colores: se cambian aquí y afectan a toda la página ===== */
    :root {
      --fondo: #eef1f7;
      --tarjeta: #ffffff;
      --texto: #1c2333;
      --texto-suave: #6b7488;
      --borde: #e1e5ee;
      --acento: #5b5bd6;          /* burbujas propias y botones */
      --acento-texto: #ffffff;
      --burbuja-otro: #f1f3f9;
      --ok: #1f9d55;
      --espera: #d69e2e;
      --error: #d64545;
    }
    /* Modo oscuro automático si el sistema operativo lo usa */
    @media (prefers-color-scheme: dark) {
      :root {
        --fondo: #0f1320;
        --tarjeta: #181d2c;
        --texto: #e8ebf3;
        --texto-suave: #98a1b6;
        --borde: #2a3145;
        --acento: #7c7cf0;
        --burbuja-otro: #232a3d;
      }
    }

    * { box-sizing: border-box; }
    body {
      margin: 0;
      min-height: 100vh;
      display: grid;
      place-items: center;
      background: var(--fondo);
      color: var(--texto);
      font-family: system-ui, -apple-system, "Segoe UI", Roboto, sans-serif;
    }

    /* ===== Tarjeta del chat ===== */
    .chat {
      width: min(680px, 100%);
      height: min(760px, 100vh);
      display: flex;
      flex-direction: column;
      background: var(--tarjeta);
      border: 1px solid var(--borde);
      border-radius: 20px;
      box-shadow: 0 20px 50px rgba(20, 30, 60, .12);
      overflow: hidden;
    }
    /* En el móvil ocupa toda la pantalla, sin bordes redondeados */
    @media (max-width: 700px) {
      .chat { height: 100vh; border-radius: 0; border: 0; }
    }

    /* ===== Cabecera ===== */
    header {
      display: flex;
      align-items: center;
      gap: 12px;
      padding: 16px 20px;
      border-bottom: 1px solid var(--borde);
    }
    header h1 { margin: 0; font-size: 1.2rem; flex: 1; }
    .estado {
      display: inline-flex;
      align-items: center;
      gap: 8px;
      font-size: .85rem;
      color: var(--texto-suave);
    }
    .estado::before {             /* el puntito de color */
      content: "";
      width: 10px; height: 10px;
      border-radius: 50%;
      background: var(--color-estado, var(--espera));
    }
    .estado.conectado    { --color-estado: var(--ok); }
    .estado.desconectado { --color-estado: var(--error); }

    /* ===== Lista de mensajes ===== */
    #mensajes {
      flex: 1;
      margin: 0;
      padding: 20px;
      list-style: none;
      overflow-y: auto;
      display: flex;
      flex-direction: column;
      gap: 10px;
    }
    .vacio { margin: auto; color: var(--texto-suave); text-align: center; }
    .burbuja {
      max-width: 75%;
      padding: 10px 14px;
      border-radius: 16px;
      background: var(--burbuja-otro);
      align-self: flex-start;      /* mensajes recibidos: a la izquierda */
      border-bottom-left-radius: 4px;
      overflow-wrap: anywhere;     /* que una palabra larguísima no rompa el diseño */
      animation: aparecer .2s ease-out;
    }
    .burbuja.mio {
      align-self: flex-end;        /* mensajes propios: a la derecha */
      background: var(--acento);
      color: var(--acento-texto);
      border-bottom-left-radius: 16px;
      border-bottom-right-radius: 4px;
    }
    .burbuja time { display: block; margin-top: 4px; font-size: .7rem; opacity: .7; text-align: right; }
    @keyframes aparecer { from { opacity: 0; transform: translateY(6px); } }

    /* ===== Barra para escribir ===== */
    form {
      display: flex;
      gap: 10px;
      padding: 14px 16px;
      border-top: 1px solid var(--borde);
    }
    input {
      flex: 1;
      padding: 12px 16px;
      font: inherit;
      color: inherit;
      background: var(--fondo);
      border: 1px solid var(--borde);
      border-radius: 999px;
    }
    button {
      padding: 10px 18px;
      font: inherit;
      font-weight: 600;
      color: var(--acento-texto);
      background: var(--acento);
      border: 0;
      border-radius: 999px;
      cursor: pointer;
      transition: filter .15s;
    }
    button:hover { filter: brightness(1.1); }
    button.secundario { background: transparent; color: var(--acento); border: 1px solid var(--borde); padding: 6px 14px; }
    button:disabled, input:disabled { opacity: .5; cursor: not-allowed; }
    input:focus-visible, button:focus-visible { outline: 3px solid var(--acento); outline-offset: 2px; }
  </style>
</head>
<body>
  <main class="chat">
    <header>
      <h1>Chat</h1>
      <span id="estado" class="estado" role="status">Conectando...</span>
      <button id="reconectar" class="secundario" type="button" hidden>Reconectar</button>
    </header>

    <ul id="mensajes" aria-live="polite">
      <li class="vacio" id="vacio">Aún no hay mensajes</li>
    </ul>

    <form id="formulario">
      <input id="texto" autocomplete="off" maxlength="500" placeholder="Escribe un mensaje..." aria-label="Mensaje" disabled>
      <button id="enviar" disabled>Enviar</button>
    </form>
  </main>

  <script>
    // Elementos de la página
    const estado     = document.getElementById("estado");
    const reconectar = document.getElementById("reconectar");
    const mensajes   = document.getElementById("mensajes");
    const vacio      = document.getElementById("vacio");
    const formulario = document.getElementById("formulario");
    const texto      = document.getElementById("texto");
    const enviar     = document.getElementById("enviar");

    let ws = null; // la conexión WebSocket actual

    // Cambia la insignia de estado y activa/desactiva la barra de escribir
    function ponerEstado(clase, etiqueta) {
      estado.className = "estado " + clase;
      estado.textContent = etiqueta;
      const abierto = clase === "conectado";
      texto.disabled = !abierto;
      enviar.disabled = !abierto;
      reconectar.hidden = clase !== "desconectado";
      if (abierto) texto.focus();
    }

    // Añade una burbuja a la lista. "mio" = true si lo escribí yo
    function agregarMensaje(contenido, mio) {
      vacio.remove(); // quita el aviso de "Aún no hay mensajes"
      const li = document.createElement("li");
      li.className = mio ? "burbuja mio" : "burbuja";
      li.textContent = contenido; // textContent: el texto se muestra tal cual, nunca se ejecuta como HTML
      const hora = document.createElement("time");
      hora.textContent = new Date().toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
      li.appendChild(hora);
      mensajes.appendChild(li);
      mensajes.scrollTop = mensajes.scrollHeight; // baja hasta el último mensaje
    }

    // Abre la conexión con la ruta /ws del servidor (ws:// en local, wss:// si la página va por https)
    function conectar() {
      ponerEstado("", "Conectando...");
      const protocolo = location.protocol === "https:" ? "wss" : "ws";
      ws = new WebSocket(protocolo + "://" + location.host + "/ws");

      ws.onopen    = () => ponerEstado("conectado", "Conectado");
      ws.onclose   = () => ponerEstado("desconectado", "Desconectado");
      ws.onmessage = (evento) => agregarMensaje(evento.data, false); // llegó texto del servidor
    }

    // Al enviar el formulario (botón o tecla Enter)
    formulario.addEventListener("submit", (e) => {
      e.preventDefault(); // evita que la página se recargue
      const mensaje = texto.value.trim();
      if (!mensaje || !ws || ws.readyState !== WebSocket.OPEN) return;
      ws.send(mensaje);
      agregarMensaje(mensaje, true);
      texto.value = "";
    });

    reconectar.addEventListener("click", conectar);
    conectar();
  </script>
</body>
</html>
"""
html_servidor = html.replace('"/ws"', '"/ws/servidor"').replace("<h1>Chat</h1>", "<h1>Panel del servidor</h1>")

clientes: set[WebSocket] = set()
serv: set[WebSocket] = set()

async def leer_consola():
    while True:
        mensaje = await asyncio.to_thread(input)
        for c in list(clientes):
            await  c.send_text(mensaje)



@asynccontextmanager
async def lifespan(app: FastAPI):
    tarea = asyncio.create_task(leer_consola())
    yield
    tarea.cancel()

app = FastAPI()

@app.get("/")
async def get():
    return HTMLResponse(content=html)

@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await websocket.accept()
    clientes.add(websocket)
    try:
        while True:
            mensaje = await websocket.receive_text()
            for s in list(serv):
                await s.send_text(f"Cliente: {mensaje}")
    except WebSocketDisconnect:
        clientes.discard(websocket)

@app.get("/servidor")
async def servidor():
    return HTMLResponse(content=html_servidor)

@app.websocket("/ws/servidor")
async def websocket_endpoint(websocket: WebSocket):
    await websocket.accept()
    serv.add(websocket)
    try:
        while True:
            mensaje = await websocket.receive_text()
            print(f"Server: {mensaje}")
            for c in list(clientes):
                await c.send_text(f"Server: {mensaje}")
    except WebSocketDisconnect:
        serv.discard(websocket)
