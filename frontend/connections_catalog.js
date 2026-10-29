/** FactoryOS Connections vNext: UI-neutral provider/worker catalog.
 * No network calls, credentials, or paid actions are performed here.
 * Backend is authoritative for connection and worker statuses.
 */
export const AI_PROVIDERS = Object.freeze([
  { id: "openai", label: "ChatGPT / OpenAI", availability: "supported", role: "ai" },
  { id: "anthropic", label: "Claude", availability: "supported", role: "ai" },
  { id: "google", label: "Gemini", availability: "supported", role: "ai" },
  { id: "microsoft", label: "Copilot", availability: "planned", role: "ai" },
  { id: "deepseek", label: "DeepSeek", availability: "planned", role: "ai" },
  { id: "xai", label: "Grok", availability: "planned", role: "ai" }
]);
export const WORKER_HOSTS = Object.freeze([
  { id: "factoryos", label: "FactoryOS backend", requiresInstall: false },
  { id: "local", label: "My computer", requiresInstall: true },
  { id: "remote", label: "Existing VPS / server", requiresInstall: true },
  { id: "cloud", label: "Cloud host", requiresInstall: true }
]);
export const WORKER_STATES = Object.freeze([
  "unpaired", "offline", "idle", "claimed", "running", "blocked", "error"
]);
export const CONNECTION_LABELS = Object.freeze({
  ru: { ai: "AI-модели и агенты", workers: "Исполнители задач", video: "Генерация видео", setup: "Добавить исполнителя", unavailable: "Пока недоступно" },
  uk: { ai: "AI-моделі та агенти", workers: "Виконавці завдань", video: "Генерація відео", setup: "Додати виконавця", unavailable: "Поки недоступно" },
  en: { ai: "AI models and agents", workers: "Task executors", video: "Video generation", setup: "Add executor", unavailable: "Not available yet" }
});
export function providerView(provider, serverConnection) {
  if (!provider || !provider.id) throw new TypeError("Provider required");
  return {
    ...provider,
    status: provider.availability === "planned" ? "coming_soon" :
      serverConnection?.verified === true ? "connected" : "not_connected",
    // Subscription is not a generic API credential.
    authentication: serverConnection?.authMethod || null
  };
}
export function workerView(worker, nowMs = Date.now(), staleAfterMs = 120000) {
  if (!worker || !worker.id) throw new TypeError("Worker id required");
  const lastSeen = worker.lastHeartbeatAt ? Date.parse(worker.lastHeartbeatAt) : NaN;
  const online = Number.isFinite(lastSeen) && nowMs - lastSeen >= 0 && nowMs - lastSeen <= staleAfterMs;
  const state = !worker.paired ? "unpaired" : !online ? "offline" :
    WORKER_STATES.includes(worker.state) ? worker.state : "idle";
  return { id: worker.id, name: worker.name, hostType: worker.hostType,
    runtime: worker.runtime, providerId: worker.providerId,
    state, lastHeartbeatAt: worker.lastHeartbeatAt || null,
    currentTaskId: online ? worker.currentTaskId || null : null };
}
export function videoCapability(provider, model, serverCapabilities = {}) {
  const capability = serverCapabilities?.[provider]?.[model];
  return { provider, model, status: capability?.verified === true &&
    capability?.videoGeneration === true ? "available" : "not_verified",
    // An API key or a text-capable Gemini model is not proof of video access.
    requiresVerification: true };
}
export const WORKER_SETUP_STEPS = Object.freeze([
  "choose_host", "choose_runtime", "authenticate", "install",
  "pair", "verify_heartbeat", "test_task"
]);
