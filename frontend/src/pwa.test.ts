import { readFileSync } from "node:fs"
import { resolve } from "node:path"
import { describe, expect, it, vi } from "vitest"
import { PHASE6_SERVICE_WORKER_PATH, registerPhase6Pwa } from "./pwa"

const publicFile = (path: string) => resolve(process.cwd(), "public", path)
const workerSource = () => readFileSync(publicFile("service-worker.js"), "utf-8")
const manifest = () => JSON.parse(readFileSync(publicFile("manifest.webmanifest"), "utf-8")) as {
  name: string
  display: string
  start_url: string
  icons: Array<{ src: string; sizes: string; type: string }>
}

describe("Phase 6 offline-lite PWA shell", () => {
  it("declares an installable app manifest with bounded shell metadata", () => {
    const parsed = manifest()

    expect(parsed.name).toContain("Agronomy Agent")
    expect(parsed.display).toBe("standalone")
    expect(parsed.start_url).toBe("/")
    expect(parsed.icons).toEqual(
      expect.arrayContaining([
        expect.objectContaining({ src: "/icons/agronomy-agent.svg", type: "image/svg+xml", sizes: "any" }),
      ]),
    )
  })

  it("does not register a service worker outside production or unsupported browsers", () => {
    expect(registerPhase6Pwa({}, window, true)).toEqual({ attempted: false, reason: "unsupported" })

    const register = vi.fn()
    const result = registerPhase6Pwa({ serviceWorker: { register } }, window, false)

    expect(result).toEqual({ attempted: false, reason: "not_production" })
    expect(register).not.toHaveBeenCalled()
  })

  it("registers the production worker at root scope", () => {
    const register = vi.fn().mockResolvedValue({})
    const addEventListener = vi.fn((event: string, callback: () => void) => {
      expect(event).toBe("load")
      callback()
    })

    const result = registerPhase6Pwa({ serviceWorker: { register } }, { addEventListener } as unknown as Window, true)

    expect(result).toEqual({ attempted: true, reason: "registered" })
    expect(register).toHaveBeenCalledWith(PHASE6_SERVICE_WORKER_PATH, { scope: "/" })
  })

  it("keeps private API and chat surfaces out of the worker cache path", () => {
    const source = workerSource()

    expect(source).toContain("request.method !== 'GET'")
    expect(source).toContain("url.origin !== self.location.origin")
    expect(source).toContain("RUNTIME_CACHE_NAME")
    expect(source).toContain("PHASE6_RUNTIME_CACHE_MAX_ENTRIES = 32")
    expect(source).toContain("trimPhase6RuntimeCache")
    expect(source).toContain("cachePhase6RuntimeAsset")
    expect(source).toContain("cache.delete(keys[index])")
    expect(source).toContain("open-agronomy-agent-shell-v2")
    expect(source).toContain("!ACTIVE_CACHE_NAMES.includes(key)")
    expect(source).toContain("event.waitUntil(cachePhase6ShellIndex(copy))")
    expect(source).toContain("event.waitUntil(cachePhase6RuntimeAsset(request, copy))")
    for (const privatePrefix of ["/api", "/auth", "/chat", "/messages", "/attachments", "/exports", "/export-jobs", "/quotas"]) {
      expect(source).toContain(`'${privatePrefix}'`)
    }

    const precacheBlock = source.slice(source.indexOf("PRECACHE_URLS"), source.indexOf("const PRIVATE_API_PREFIXES"))
    expect(precacheBlock).not.toContain("/api")
    expect(precacheBlock).not.toContain("/chat")
    expect(precacheBlock).not.toContain("/messages")
    expect(precacheBlock).not.toContain("/attachments")
    expect(precacheBlock).not.toContain("/exports")
    expect(precacheBlock).not.toContain("/export-jobs")
  })
})
