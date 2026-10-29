import json
import logging
from datetime import datetime
from functools import lru_cache
from pathlib import Path
from zoneinfo import ZoneInfo

from langchain_openai import ChatOpenAI
from langchain_core.messages import SystemMessage, HumanMessage, ToolMessage
from langchain_core.tools import BaseTool

from app.config import settings

logger = logging.getLogger(__name__)

_RESPUESTA_VACIA = "No pude generar una respuesta. Hay algo más en lo que te pueda ayudar?"
_ERROR_HERRAMIENTA = "Ocurrió un error al ejecutar la herramienta. Intenta de nuevo."

_RUTA_PROMPT = Path(__file__).resolve().parents[1] / "prompts" / "trackr.txt"


@lru_cache(maxsize=1)
def _plantilla_prompt() -> str:
    return _RUTA_PROMPT.read_text(encoding="utf-8")


@lru_cache(maxsize=1)
def _modelo() -> ChatOpenAI:
    return ChatOpenAI(
        model=settings.MODEL_AGENTE,
        temperature=0,
        max_tokens=1000,
        api_key=settings.OPENROUTER_API_KEY,
        base_url=settings.OPENROUTER_API_BASE_URL,
    )


def _system_prompt() -> str:
    ahora = datetime.now(ZoneInfo(settings.TIMEZONE))
    return _plantilla_prompt().replace(
        "{{current_time}}",
        f"{ahora.isoformat()} ({settings.TIMEZONE})",
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
    model = _modelo()
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
                except Exception:
                    logger.exception("Error al ejecutar la herramienta %s", tool_call["name"])
                    observation = _ERROR_HERRAMIENTA

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

    respuesta = str(response.content).strip()
    return (respuesta or _RESPUESTA_VACIA), used_tools
