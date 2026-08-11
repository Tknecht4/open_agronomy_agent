type ServiceWorkerContainerLike = {
  register: (scriptURL: string, options?: RegistrationOptions) => Promise<unknown>
}

type NavigatorLike = {
  serviceWorker?: ServiceWorkerContainerLike
}

type WindowLike = {
  addEventListener: Window["addEventListener"]
}

export type Phase6PwaRegistration = {
  attempted: boolean
  reason: "unsupported" | "not_production" | "registered"
}

export const PHASE6_SERVICE_WORKER_PATH = "/service-worker.js"

export function registerPhase6Pwa(
  navigatorLike: NavigatorLike = navigator,
  windowLike: WindowLike = window,
  production = import.meta.env.PROD,
): Phase6PwaRegistration {
  if (!navigatorLike.serviceWorker) {
    return { attempted: false, reason: "unsupported" }
  }
  if (!production) {
    return { attempted: false, reason: "not_production" }
  }

  const register = () => {
    navigatorLike.serviceWorker
      ?.register(PHASE6_SERVICE_WORKER_PATH, { scope: "/" })
      .catch((error: unknown) => {
        console.warn("Phase 6 PWA service worker registration failed", error)
      })
  }

  if (document.readyState === "complete") {
    register()
  } else {
    windowLike.addEventListener("load", register, { once: true })
  }

  return { attempted: true, reason: "registered" }
}
