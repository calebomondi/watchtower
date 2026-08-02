import operator
import time
import json
from pydantic import BaseModel, Field
from typing import Annotated, Any, Literal, Sequence
from typing_extensions import TypedDict

from langchain_tavily import TavilySearch
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, get_buffer_string
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_qwq import ChatQwen
from langchain_groq import ChatGroq
from langgraph.constants import Send
from langgraph.graph import END, MessagesState, START, StateGraph
from langgraph.checkpoint.memory import MemorySaver
from langgraph.checkpoint.serde.jsonplus import JsonPlusSerializer

import logging
from config import Config

logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(name)s %(message)s")
logging.getLogger("WatchTower").setLevel(logging.INFO)
logger = logging.getLogger("watchtower.nodes")
cfg = Config()

### LLM

GOOGLE_MODELS = [
    "gemini-2.5-flash",
    "gemini-3.5-flash"
]

GROQ_MODELS = [
    "llama-3.3-70b-versatile",
]

QWEN_MODELS = [
    # "qwen3.7-plus",
    "qwen3.7-max"
]


def _llm(provider: str = "gemini", model: str | None = None):
    if provider == "groq":
        m = model or GROQ_MODELS[0]
        logger.info("Using Groq (%s)", m)
        return ChatGroq(
            model=m,
            groq_api_key=cfg.groq_api_key,
            temperature=0,
        )

    elif provider == "qwen":
        m = model or QWEN_MODELS[0]
        logger.info("Using Qwen (%s)", m)

        return ChatQwen(
            model=m,
            api_key=cfg.dashscope_api_key,
            base_url=cfg.dashscope_base_url,
            extra_body={"enable_thinking": False},
        )

    m = model or GOOGLE_MODELS[0]
    logger.info("Using Gemini (%s)", m)
    return ChatGoogleGenerativeAI(
        model=m,
        google_api_key=cfg.google_api_key,
        temperature=0,
    )


def _invoke_structured_with_fallback(
    messages: Sequence[Any],
    schema: Any | None = None,
    providers: list[tuple[str, list[str]]] | None = None,
    log_label: str = "LLM call",
    max_retries: int = 2,
):
    """
    Invoke an LLM across a prioritized list of (provider, [models]) pairs,
    falling back on failure. Retries on 429/rate-limit errors with backoff.
    If `schema` is provided, uses structured output; otherwise does a plain invoke.
    """
    if providers is None:
        providers = [
            ("gemini", GOOGLE_MODELS), 
            ("groq", GROQ_MODELS), 
            ("qwen", QWEN_MODELS)
        ]

    last_err = None
    for provider, models in providers:
        for model in models:
            for attempt in range(1, max_retries + 1):
                try:
                    llm = _llm(provider, model=model)
                    if schema is not None:
                        llm = llm.with_structured_output(schema)
                    result = llm.invoke(messages)
                    logger.info("%s succeeded with %s/%s", log_label, provider, model)
                    return result
                except Exception as e:
                    last_err = e
                    err_str = str(e).lower()
                    is_rate_limit = "429" in err_str or "rate_limit" in err_str
                    logger.warning(
                        "%s failed with %s/%s (attempt %d/%d): %s",
                        log_label, provider, model, attempt, max_retries, e,
                    )
                    if is_rate_limit and attempt < max_retries:
                        import re
                        match = re.search(r"try again in ([\d.]+)s", str(e))
                        delay = float(match.group(1)) if match else 1.5 * (2 ** (attempt - 1))
                        logger.info("Rate limited, retrying in %.1fs...", delay)
                        time.sleep(delay)
                        continue
                    break

    raise RuntimeError(f"All LLM providers failed for {log_label}") from last_err


### Schema


class Analyst(BaseModel):
    affiliation: str = Field(
        description="Primary affiliation of the analyst.",
    )
    name: str = Field(
        description="Name of the analyst."
    )
    role: str = Field(
        description="Role of the analyst in the context of the prediction market topic.",
    )
    description: str = Field(
        description="Description of the analyst focus, concerns, and motives regarding this prediction market.",
    )

    @property
    def persona(self) -> str:
        return f"Name: {self.name}\nRole: {self.role}\nAffiliation: {self.affiliation}\nDescription: {self.description}\n"


class Perspectives(BaseModel):
    analysts: list[Analyst] = Field(
        description="Comprehensive list of analysts with their roles and affiliations.",
    )


class MarketDecision(BaseModel):
    decision: Literal["YES", "NO", "MAYBE"] = Field(
        description="The prediction: YES if the event will happen, NO if not, MAYBE if uncertain."
    )
    confidence: float = Field(
        ge=0, le=100,
        description="Confidence level from 0 to 100."
    )
    reasoning: str = Field(
        description="Consolidated reasoning for the decision, referencing analyst memos and market data."
    )
    sources: list[str] = Field(
        description="All sources cited in the analysis."
    )



class InterviewState(MessagesState):
    max_num_turns: int
    context: Annotated[list, operator.add]
    analyst: Analyst
    interview: str
    sections: list
    section_word_count: int


class SearchQuery(BaseModel):
    search_query: str = Field(None, description="Search query for retrieval.")


memory = MemorySaver(serde=JsonPlusSerializer().with_msgpack_allowlist([Analyst]))


class PredictionMarketState(TypedDict):
    topic: str
    max_analysts: int
    human_analyst_feedback: str
    analysts: list[Analyst]
    sections: Annotated[list, operator.add]
    final_decision: str
    confidence: float
    reasoning: str
    sources: list[str]
    final_output: str


### Nodes and edges

analyst_instructions = """You are tasked with creating a set of AI analyst personas for evaluating a prediction market question. Follow these instructions carefully:

1. First, review the prediction market question:
{topic}

2. Examine any editorial feedback that has been optionally provided to guide creation of the analysts:
{human_analyst_feedback}

3. Determine the most interesting and relevant analytical perspectives for evaluating this prediction. Consider:
- Domain expertise relevant to the question
- Contrarian viewpoints that could challenge the crowd consensus
- Quantitative/statistical analysis perspectives
- Sentiment and momentum analysis
- Risk assessment and scenario analysis

4. Pick the top {max_analysts} perspectives.

5. Assign one analyst to each perspective."""


def create_analysts(state: PredictionMarketState):
    """Create analysts"""
    topic = state["topic"]
    max_analysts = state["max_analysts"]
    human_analyst_feedback = state.get("human_analyst_feedback", "")

    system_message = analyst_instructions.format(
        topic=topic,
        human_analyst_feedback=human_analyst_feedback,
        max_analysts=max_analysts,
    )

    analysts = _invoke_structured_with_fallback(
        messages=[
            SystemMessage(content=system_message),
            HumanMessage(content="Generate the set of analysts."),
        ],
        schema=Perspectives,
        log_label="create_analysts",
    )

    logger.info("Analysts Created: %s", analysts.analysts)
    return {"analysts": analysts.analysts}


question_instructions = """You are an analyst tasked with investigating a prediction market question to form an evidence-based opinion.

Your goal is to gather specific, actionable evidence that will help determine whether the predicted event will occur.

1. Evidence For: Find specific data points, trends, or expert opinions supporting the event happening.

2. Evidence Against: Find specific data points, trends, or expert opinions suggesting the event will NOT happen.

3. Market Signals: Consider what the current prediction market odds imply and whether they seem mispriced.

Here is your topic of focus and set of goals: {goals}

Begin by introducing yourself using a name that fits your persona, and then ask your first investigative question.

Continue to ask questions to drill down into the strongest evidence on both sides.

When you are satisfied with your understanding of the evidence landscape, complete the interview with: "Thank you so much for your help!"

Remember to stay in character throughout your response, reflecting the analyst persona and goals provided to you."""


def generate_question(state: InterviewState):
    """Node to generate a question"""
    analyst = state["analyst"]
    messages = state["messages"]

    system_message = question_instructions.format(goals=analyst.persona)

    question = _invoke_structured_with_fallback(
        messages=[SystemMessage(content=system_message)] + messages,
        log_label="generate_question",
    )

    logger.info("Question Generated: %s", question.content)
    return {"messages": [question]}


search_instructions = SystemMessage(content="""You will be given a conversation between an analyst investigating a prediction market question.

Your goal is to generate a well-structured web search query to find evidence relevant to the prediction.

First, analyze the full conversation.

Pay particular attention to the final question posed by the analyst.

Convert this final question into a well-structured web search query that will find factual evidence, expert analysis, or data relevant to evaluating the prediction.
""")


def _invoke_tavily_with_retry(
    query: str,
    max_results: int = 3,
    max_retries: int = 3,
    backoff_seconds: float = 1.0,
    log_label: str = "Tavily search",
):
    """
    Run a Tavily search with retry on transient failures.
    Retries max_retries times with linear backoff, then raises.
    """
    tavily_search = TavilySearch(max_results=max_results)

    last_err = None
    for attempt in range(1, max_retries + 1):
        try:
            data = tavily_search.invoke({"query": query})
            search_docs = data.get("results", data)
            logger.info("%s succeeded on attempt %d", log_label, attempt)
            return search_docs
        except Exception as e:
            last_err = e
            logger.warning(
                "%s failed on attempt %d/%d: %s", log_label, attempt, max_retries, e
            )
            if attempt < max_retries:
                time.sleep(backoff_seconds * attempt)
            continue

    raise RuntimeError(f"{log_label} failed after {max_retries} attempts") from last_err


def search_web(state: InterviewState):
    """Retrieve docs from web search"""
    search_query = _invoke_structured_with_fallback(
        messages=[search_instructions] + state["messages"],
        schema=SearchQuery,
        log_label="search_web:search_query",
    )
    logger.info("Search query Tavily: %s", search_query.search_query)

    search_docs = _invoke_tavily_with_retry(
        query=search_query.search_query,
        log_label="search_web:tavily",
    )
    logger.info("Search docs Tavily: %s", search_docs)

    formatted_search_docs = "\n\n---\n\n".join(
        [
            f'<Document href="{doc["url"]}"/>\n{doc["content"]}\n</Document>'
            for doc in search_docs
        ]
    )

    return {"context": [formatted_search_docs]}


answer_instructions = """You are a domain expert being interviewed by an analyst investigating a prediction market question.

Here is the analyst's area of focus: {goals}

You goal is to answer the analyst's question with evidence-based reasoning.

To answer the question, use this context from web research:
{context}

When answering questions, follow these guidelines:

1. Use the information provided in the context to form your opinion.

2. Be specific — cite data points, statistics, dates, and expert opinions.

3. Consider both sides: what evidence supports the event happening, and what evidence contradicts it.

4. Include sources next to relevant statements using [1], [2], etc.

5. List your sources in order at the bottom of your answer.

7. If the source is from a Document tag, cite the URL.
"""


def generate_answer(state: InterviewState):
    """Node to answer a question"""
    analyst = state["analyst"]
    messages = state["messages"]
    context = state["context"]

    system_message = answer_instructions.format(
        goals=analyst.persona,
        context=context,
    )

    answer = _invoke_structured_with_fallback(
        messages=[SystemMessage(content=system_message)] + messages,
        log_label="generate_answer",
    )
    logger.info("Answer Generated: %s", answer.content)

    answer.name = "expert"
    return {"messages": [answer]}


def save_interview(state: InterviewState):
    """Save interviews"""
    messages = state["messages"]
    interview = get_buffer_string(messages)
    return {"interview": interview}


def route_messages(state: InterviewState, name: str = "expert"):
    """Route between question and answer"""
    messages = state["messages"]
    max_num_turns = state.get("max_num_turns", 1)

    num_responses = len(
        [m for m in messages if isinstance(m, AIMessage) and m.name == name]
    )

    if num_responses >= max_num_turns:
        return "save_interview"

    last_question = messages[-2]

    if "Thank you so much for your help" in last_question.content:
        return "save_interview"
    return "ask_question"


opinion_writer_instructions = """You are an expert analyst writing an opinion memo for a prediction market evaluation.

Your task is to write a concise, evidence-based opinion memo based on an interview investigation.

1. Analyze the evidence gathered during the interview.

2. Write your memo following this structure:

a. Title (## header) — your analyst focus area
b. Key Evidence (### header) — the strongest evidence for and against
c. Assessment (### header) — your evaluation of the likelihood and confidence
d. Sources (### header)

3. For the Key Evidence section:
- List specific evidence supporting the event happening (bull case)
- List specific evidence against the event happening (bear case)
- Note any uncertainties or information gaps
- Aim for approximately {word_count} words maximum

4. For the Assessment section:
- Evaluate the likelihood of the predicted outcome based on your evidence
- Provide your conviction level (high/medium/low)

5. In the Sources section:
- Include all sources used
- Provide full links
- No redundant sources

6. Do not mention interviewer or expert names.
"""


def write_opinion(state: InterviewState):
    """Node to write an opinion memo"""
    context = state["context"]
    analyst = state["analyst"]

    system_message = opinion_writer_instructions.format(
        focus=analyst.description,
        word_count=state.get("section_word_count", 400),
    )

    section = _invoke_structured_with_fallback(
        messages=[
            SystemMessage(content=system_message),
            HumanMessage(content=f"Use this source to write your opinion memo: {context}"),
        ],
        log_label="write_opinion",
    )

    return {"sections": [section.content]}


def interviewBuilder():
    """Build the interview sub-graph"""
    interview_builder = StateGraph(InterviewState)
    interview_builder.add_node("ask_question", generate_question)
    interview_builder.add_node("search_web", search_web)
    interview_builder.add_node("answer_question", generate_answer)
    interview_builder.add_node("save_interview", save_interview)
    interview_builder.add_node("write_opinion", write_opinion)

    interview_builder.add_edge(START, "ask_question")
    interview_builder.add_edge("ask_question", "search_web")
    interview_builder.add_edge("search_web", "answer_question")
    interview_builder.add_conditional_edges(
        "answer_question", route_messages, ["ask_question", "save_interview"]
    )
    interview_builder.add_edge("save_interview", "write_opinion")
    interview_builder.add_edge("write_opinion", END)

    return interview_builder.compile()


def initiate_all_interviews(state: PredictionMarketState):
    """Kick off interviews in parallel via Send() API, auto-distributing word count."""
    topic = state["topic"]
    total = state.get("max_analysts", 3)
    section_limit = 400

    return [
        Send(
            "conduct_interview",
            {
                "analyst": analyst,
                "section_word_count": section_limit,
                "messages": [
                    HumanMessage(
                        content=f"Investigating prediction market question: {topic}"
                    ),
                ],
            },
        )
        for analyst in state["analysts"]
    ]


decision_instructions = """You are a prediction market analyst synthesizing multiple expert opinions into a final decision.

Prediction Market Question: {topic}

You have received opinion memos from {num_analysts} expert analysts. Each has investigated the question from different angles.

Your task:

1. Read all analyst memos carefully.
2. Identify the strongest evidence for and against the outcome.
3. Make a final prediction: YES (event will happen), NO (event will not happen), or MAYBE (insufficient evidence or genuinely uncertain).
4. Assign a confidence level (0-100).
5. Write a clear, concise reasoning paragraph.

Output a structured decision with:
- decision: YES, NO, or MAYBE
- confidence: 0-100
- reasoning: Your consolidated reasoning
- sources: All sources cited across the memos

Be calibrated: if the evidence is strong and consistent across analysts, confidence should be higher. If analysts disagree or evidence is thin, confidence should be lower.
"""


def write_decision(state: PredictionMarketState):
    """Synthesize all opinion memos into a final structured decision."""
    sections = state["sections"]
    topic = state["topic"]
    num_analysts = len(state.get("analysts", []))

    formatted_memos = "\n\n".join([f"--- Analyst Memo ---\n{section}" for section in sections])

    system_message = decision_instructions.format(
        topic=topic,
        num_analysts=num_analysts,
    )

    decision = _invoke_structured_with_fallback(
        messages=[
            SystemMessage(content=system_message),
            HumanMessage(content=f"Here are the analyst memos:\n\n{formatted_memos}\n\nWrite your final decision."),
        ],
        schema=MarketDecision,
        log_label="write_decision",
    )

    return {
        "final_decision": decision.decision,
        "confidence": decision.confidence,
        "reasoning": decision.reasoning,
        "sources": decision.sources,
    }


def build_decision(state: PredictionMarketState):
    """Assemble the final decision output."""
    decision = state.get("final_decision", "MAYBE")
    confidence = state.get("confidence", 0)
    reasoning = state.get("reasoning", "No reasoning provided.")
    sources = state.get("sources", [])
    topic = state.get("topic", "Unknown")

    return {"final_output": json.dumps({
        "question": topic,
        "decision": decision,
        "confidence": confidence,
        "reasoning": reasoning,
        "sources": sources,
    })}


def build_agent():
    """Build the prediction market opinion agent."""
    builder = StateGraph(PredictionMarketState)
    builder.add_node("create_analysts", create_analysts)
    builder.add_node("conduct_interview", interviewBuilder())
    builder.add_node("write_decision", write_decision)
    builder.add_node("build_decision", build_decision)

    builder.add_edge(START, "create_analysts")
    builder.add_conditional_edges(
        "create_analysts",
        initiate_all_interviews,
        ["conduct_interview"],
    )
    builder.add_edge("conduct_interview", "write_decision")
    builder.add_edge("write_decision", "build_decision")
    builder.add_edge("build_decision", END)

    return builder.compile(checkpointer=memory)
