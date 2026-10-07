import json
from datetime import datetime
from zoneinfo import ZoneInfo

from langchain_openai import ChatOpenAI
from langchain_core.messages import SystemMessage, HumanMessage, ToolMessage
from langchain_core.tools import BaseTool

from app.config import settings


def _system_prompt() -> str:
    tz = ZoneInfo(settings.TIMEZONE)
    ahora = datetime.now(tz)
    return (
        "Eres Trackr, un asistente para pequeños negocios. "
        "Solo puedes usar las herramientas que tienes disponibles. "
        "NUNCA escribas SQL ni modifiques la base de datos directamente. "
        "Cuando el usuario pida crear un recordatorio, usa la herramienta crear_recordatorio. "
        "Cuando quiera ver sus recordatorios, usa listar_recordatorios. "
        "Las fechas debes enviarlas en ISO 8601 con zona horaria explícita "
        "(por ejemplo 2026-10-08T17:00:00-06:00). "
        "Siempre repite la fecha interpretada en tu respuesta final de forma clara "
        "(por ejemplo: 'jueves 8 oct, 5:00 PM'), para que el usuario detecte errores de AM/PM. "
        f"La zona horaria del negocio es {settings.TIMEZONE}. "
        f"Fecha/hora actual: {ahora.isoformat()}. "
        "Si no entiendes una fecha, pide aclaración. "
        "Hoy solo manejas recordatorios."
    )


async def run_agent(
    mensaje: str,
    tools: list[BaseTool],
    usuario,
) -> tuple[str, list[tuple[str, str, str]]]:
    """
    Ejecuta un turno del agente.

    Retorna:
        - respuesta final del asistente
        - lista de tuplas (nombre_herramienta, args_json, resultado)
    """
    model = ChatOpenAI(
        model=settings.MODEL_AGENTE,
        temperature=0,
        max_tokens=512,
        api_key=settings.OPENROUTER_API_KEY,
        base_url=settings.OPENROUTER_API_BASE_URL,
    )
    if tools:
        model = model.bind_tools(tools)

    messages = [
        SystemMessage(content=_system_prompt()),
        HumanMessage(content=mensaje),
    ]

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

        response = await model.ainvoke(messages)
        iteration += 1

    return str(response.content), used_tools
