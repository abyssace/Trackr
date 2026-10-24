import json
from datetime import datetime
from zoneinfo import ZoneInfo

from langchain_openai import ChatOpenAI
from langchain_core.messages import SystemMessage, HumanMessage, ToolMessage
from langchain_core.tools import BaseTool

from app.config import settings
from app.servicios.inventario import normalizar_busqueda

_HERRAMIENTAS_RESPUESTA_DIRECTA = {
    "consultar_existencia",
    "listar_stock_bajo",
    "consultar_estado_pedido",
    "contar_productos_activos",
    "actualizar_stock_minimo",
}


def _respuesta_directa_herramientas(
    llamadas: list[tuple[str, str, str]],
) -> str | None:
    """Devuelve resultados verificables tal cual, sin tablas ni añadidos del LLM."""
    if llamadas and all(nombre in _HERRAMIENTAS_RESPUESTA_DIRECTA for nombre, _, _ in llamadas):
        return "\n".join(resultado for _, _, resultado in llamadas)
    return None


def _solicita_conteo_productos_activos(mensaje: str) -> bool:
    texto = normalizar_busqueda(mensaje)
    solicita_cantidad = any(
        termino in texto
        for termino in ("cuantos", "cuantas", "cantidad", "numero", "total")
    )
    consulta_compuesta_o_de_precio = " y " in f" {texto} " or any(
        termino in texto for termino in ("precio", "costo", "valor", "cuesta", "vale")
    )
    return (
        solicita_cantidad
        and "producto" in texto
        and "activo" in texto
        and not consulta_compuesta_o_de_precio
    )


def _system_prompt() -> str:
    tz = ZoneInfo(settings.TIMEZONE)
    ahora = datetime.now(tz)
    return (
        "Eres Trackr, el asistente de un pequeño negocio. "
        "Habla siempre en español sencillo, natural, amable y breve. "
        "Responde directamente a lo que preguntaron; normalmente usa una o dos frases. "
        "No uses tablas, títulos Markdown, negritas, emojis ni listas largas. "
        "Usa viñetas cortas solo cuando haya varios resultados. "
        "No agregues recomendaciones, urgencia ni explicaciones que no te pidieron. "
        "Cuando una herramienta entregue cantidades, conserva exactamente sus nombres y números; "
        "no hagas cálculos contradictorios ni inventes datos. "
        "Solo puedes usar las herramientas que tienes disponibles. "
        "NUNCA escribas SQL ni modifiques la base de datos directamente. "
        "Cuando el usuario pida crear un recordatorio, usa la herramienta crear_recordatorio. "
        "Cuando quiera ver sus recordatorios, usa listar_recordatorios. "
        "Para saber cuántos productos activos hay, usa contar_productos_activos. "
        "Puedes consultar existencias, listar productos bajo mínimo, cambiar el mínimo de un producto "
        "con actualizar_stock_minimo y consultar el estado de pedidos. "
        "La herramienta actualizar_stock_minimo crea una acción pendiente: solicita y espera confirmación "
        "antes de decir que el cambio quedó hecho. "
        "No ejecutes escrituras de inventario, pedidos o clientes sin confirmación. "
        "Las fechas debes enviarlas en ISO 8601 con zona horaria explícita "
        "(por ejemplo 2026-10-08T17:00:00-06:00). "
        "Siempre repite la fecha interpretada en tu respuesta final de forma clara "
        "(por ejemplo: 'jueves 8 oct, 5:00 PM'), para que el usuario detecte errores de AM/PM. "
        f"La zona horaria del negocio es {settings.TIMEZONE}. "
        f"Fecha/hora actual: {ahora.isoformat()}. "
        "Si no entiendes una fecha, pide aclaración. "
        "Para buscar productos o pedidos, usa el texto libre del usuario; nunca inventes ids ni SKU. "
        "No digas que una función no existe si una herramienta disponible puede realizarla. "
        "Si no hay resultados, dilo de forma directa y breve."
    )


async def run_agent(
    mensaje: str,
    tools: list[BaseTool],
    usuario,
    historial: list | None = None,
) -> tuple[str, list[tuple[str, str, str]]]:
    """
    Ejecuta un turno del agente.

    Args:
        historial: lista de mensajes previos (HumanMessage / AIMessage).

    Retorna:
        - respuesta final del asistente
        - lista de tuplas (nombre_herramienta, args_json, resultado)
    """
    if _solicita_conteo_productos_activos(mensaje):
        count_tool = next(
            (t for t in tools if t.name == "contar_productos_activos"),
            None,
        )
        if count_tool is not None:
            resultado = str(await count_tool.ainvoke({}))
            return resultado, [(count_tool.name, "{}", resultado)]

    model = ChatOpenAI(
        model=settings.MODEL_AGENTE,
        temperature=0,
        max_tokens=512,
        api_key=settings.OPENROUTER_API_KEY,
        base_url=settings.OPENROUTER_API_BASE_URL,
    )
    if tools:
        model = model.bind_tools(tools)

    messages = [SystemMessage(content=_system_prompt())]
    if historial:
        messages.extend(historial)
    messages.append(HumanMessage(content=mensaje))

    used_tools: list[tuple[str, str, str]] = []
    response = await model.ainvoke(messages)

    max_iterations = 3
    iteration = 0
    while response.tool_calls and iteration < max_iterations:
        messages.append(response)

        for tool_call in response.tool_calls:
            tool = next(
                (t for t in tools if t.name == tool_call["name"]),
                None,
            )
            if tool is None:
                observation = f"Herramienta desconocida: {tool_call['name']}"
            else:
                try:
                    observation = await tool.ainvoke(tool_call["args"])
                except Exception as exc:
                    observation = f"Error al ejecutar la herramienta: {exc}"

            used_tools.append(
                (
                    tool_call["name"],
                    json.dumps(tool_call.get("args", {}), ensure_ascii=False),
                    str(observation),
                )
            )
            messages.append(
                ToolMessage(
                    content=str(observation),
                    tool_call_id=tool_call["id"],
                )
            )

        respuesta_directa = _respuesta_directa_herramientas(used_tools)
        if respuesta_directa is not None:
            return respuesta_directa, used_tools

        response = await model.ainvoke(messages)
        iteration += 1

    return str(response.content), used_tools
