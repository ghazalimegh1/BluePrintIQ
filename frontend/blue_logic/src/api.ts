import type {
  Answer,
  DocumentRecord,
  LlmStatus,
  SceneResponse,
} from "./types";

async function request<T>(url: string, init?: RequestInit): Promise<T> {
  const response = await fetch(url, init);
  if (!response.ok) {
    let message = `${response.status} ${response.statusText}`;
    try {
      const body = await response.json() as { detail?: string };
      message = body.detail || message;
    } catch {
      // Use the HTTP status when the response has no JSON error body.
    }
    throw new Error(message);
  }
  return response.json() as Promise<T>;
}

export const api = {
  documents: () => request<DocumentRecord[]>("/api/documents"),
  document: (id: string) =>
    request<DocumentRecord>(`/api/documents/${encodeURIComponent(id)}`),
  llmStatus: () => request<LlmStatus>("/api/llm/status"),
  scene: (id: string, limit = 100, offset = 0) =>
    request<SceneResponse>(
      `/api/documents/${encodeURIComponent(id)}/scene?limit=${limit}&offset=${offset}`,
    ),
  selectedElements: (id: string, elementIds: string[]) =>
    request<SceneResponse>(`/api/documents/${encodeURIComponent(id)}/scene/elements`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ element_ids: elementIds }),
    }),
  ask: (
    documentId: string,
    question: string,
    page: number,
    allowGroq: boolean,
    allowGemini: boolean,
    groqModel: string,
  ) => request<Answer>("/api/ask", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      document_id: documentId,
      question,
      page_number: page,
      llm: allowGroq ? { provider: "groq", model: groqModel } : null,
      gemini_vl_consent: allowGemini,
    }),
  }),
  upload: async (file: File) => {
    const response = await fetch("/api/upload", {
      method: "POST",
      headers: { "X-Filename": file.name },
      body: file,
    });
    if (!response.ok) {
      let message = `${response.status} ${response.statusText}`;
      try {
        const body = await response.json() as { detail?: string };
        message = body.detail || message;
      } catch {
        // Use the HTTP status when the response has no JSON error body.
      }
      throw new Error(message);
    }
    return response.json() as Promise<DocumentRecord>;
  },
  preview: async (id: string, page: number) => {
    const response = await fetch(
      `/api/documents/${encodeURIComponent(id)}/preview?page=${page}`,
    );
    if (!response.ok) {
      let message = `${response.status} ${response.statusText}`;
      try {
        const body = await response.json() as { detail?: string };
        message = body.detail || message;
      } catch {
        // Use the HTTP status when the response has no JSON error body.
      }
      throw new Error(message);
    }
    return {
      url: URL.createObjectURL(await response.blob()),
      width: Number(response.headers.get("X-Page-Width")) || 0,
      height: Number(response.headers.get("X-Page-Height")) || 0,
      pageCount: Number(response.headers.get("X-Page-Count")) || 1,
      viewBox: response.headers.get("X-Page-Viewbox"),
      coordinateSystem: response.headers.get("X-Coordinate-System") || "unknown",
    };
  },
};
