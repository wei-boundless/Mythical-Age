import type { RetrievalResult, ToolCall } from "@/lib/api";

import type { Message, StoreState } from "./types";
import {
  looksLikeSkillDocument,
  looksLikeSkillDocumentPrefix,
  makeId,
  sanitizeToolCall
} from "./utils";

export type StreamSession = {
  assistantId: string;
  hiddenToolCallInFlight: boolean;
};

type StreamTransition = {
  state: StoreState;
  session: StreamSession;
};

function patchAssistant(
  state: StoreState,
  assistantId: string,
  updater: (message: Message) => Message
): StoreState {
  return {
    ...state,
    messages: state.messages.map((message) =>
      message.id === assistantId ? updater(message) : message
    )
  };
}

export function startStreamingTurn(state: StoreState, userContent: string): StreamTransition {
  const userMessage: Message = {
    id: makeId(),
    role: "user",
    content: userContent.trim(),
    toolCalls: [],
    retrievals: []
  };
  const assistantMessage: Message = {
    id: makeId(),
    role: "assistant",
    content: "",
    toolCalls: [],
    retrievals: []
  };

  return {
    state: {
      ...state,
      isStreaming: true,
      messages: [...state.messages, userMessage, assistantMessage]
    },
    session: {
      assistantId: assistantMessage.id,
      hiddenToolCallInFlight: false
    }
  };
}

export function reduceStreamEvent(
  state: StoreState,
  session: StreamSession,
  event: string,
  data: Record<string, unknown>
): StreamTransition {
  if (event === "retrieval") {
    return {
      state: patchAssistant(state, session.assistantId, (message) => ({
        ...message,
        retrievals: (data.results as RetrievalResult[]) ?? []
      })),
      session
    };
  }

  if (event === "token") {
    return {
      state: patchAssistant(state, session.assistantId, (message) => {
        const nextContent = `${message.content}${String(data.content ?? "")}`;
        if (
          (!message.content.trim() && looksLikeSkillDocumentPrefix(nextContent)) ||
          looksLikeSkillDocument(nextContent)
        ) {
          return message;
        }
        return { ...message, content: nextContent };
      }),
      session
    };
  }

  if (event === "tool_start") {
    const rawToolCall: ToolCall = {
      tool: String(data.tool ?? "tool"),
      input: String(data.input ?? ""),
      output: ""
    };
    const toolCall = sanitizeToolCall(rawToolCall);
    const hiddenToolCallInFlight = !toolCall;
    if (!toolCall) {
      return {
        state,
        session: { ...session, hiddenToolCallInFlight }
      };
    }
    return {
      state: patchAssistant(state, session.assistantId, (message) => ({
        ...message,
        toolCalls: [...message.toolCalls, toolCall]
      })),
      session: { ...session, hiddenToolCallInFlight }
    };
  }

  if (event === "tool_end") {
    if (session.hiddenToolCallInFlight) {
      return {
        state,
        session: { ...session, hiddenToolCallInFlight: false }
      };
    }
    return {
      state: patchAssistant(state, session.assistantId, (message) => ({
        ...message,
        toolCalls: message.toolCalls.flatMap((toolCall, index, list) => {
          if (index !== list.length - 1) {
            return [toolCall];
          }
          const sanitized = sanitizeToolCall({
            ...toolCall,
            output: String(data.output ?? "")
          });
          return sanitized ? [sanitized] : [];
        })
      })),
      session
    };
  }

  if (event === "done") {
    return {
      state: patchAssistant(state, session.assistantId, (message) =>
        message.content
          ? message
          : {
              ...message,
              content: String(data.content ?? "")
            }
      ),
      session
    };
  }

  if (event === "error") {
    return {
      state: patchAssistant(state, session.assistantId, (message) => ({
        ...message,
        content: message.content || `Request failed: ${String(data.error ?? "unknown error")}`
      })),
      session
    };
  }

  return { state, session };
}
