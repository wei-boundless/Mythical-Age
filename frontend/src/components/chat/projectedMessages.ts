import type { ChronologicalProjectionView } from "@/lib/projection/chronological";
import type { Message, StoreState } from "@/lib/store/types";

type LegacyProjectionMessage = Message & {
  projectionView?: ChronologicalProjectionView;
};

export type ProjectedMessage = Message & {
  projectionView?: ChronologicalProjectionView;
};

export function messagesWithActiveProjectionViews(
  messages: Message[],
  activeProjectionsByKey: StoreState["activeProjectionsByKey"],
): ProjectedMessage[] {
  return messages.map((message) => {
    const baseMessage = withoutLegacyProjectionView(message);
    const key = String(message.projectionKeyString ?? "").trim();
    const projectionView = key ? activeProjectionsByKey[key]?.view : undefined;
    return projectionView ? { ...baseMessage, projectionView } : baseMessage;
  });
}

function withoutLegacyProjectionView(message: Message): Message {
  const { projectionView: _discarded, ...rest } = message as LegacyProjectionMessage;
  return rest;
}
