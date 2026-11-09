export type Role = "admin" | "manager" | "user";

export type ViewKey =
  | "dashboard"
  | "models"
  | "knowledge"
  | "assistants"
  | "chat"
  | "logs"
  | "datasets"
  | "settings";

export type ToastMessage = {
  id: number;
  title: string;
  description?: string;
  tone?: "success" | "warning" | "info";
};

export type KnowledgeBase = {
  id: string;
  name: string;
  description: string;
  icon: string;
  tone: string;
  documents: number;
  chunks: number;
  updatedAt: string;
  embedding: string;
  state: "ready" | "building" | "empty" | "failed" | "archived";
};

export type Assistant = {
  id: string;
  name: string;
  description: string;
  avatar: string;
  knowledgeBases: string[];
  model: string;
  sessions: number;
  updatedAt: string;
  status: "online" | "draft";
};
