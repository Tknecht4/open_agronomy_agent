import '@testing-library/jest-dom/vitest'

import { beforeEach } from 'vitest'
import { testLocks } from '../fieldEventTestSupport'
beforeEach(() => Object.defineProperty(navigator, 'locks', { configurable: true, value: testLocks() }))
