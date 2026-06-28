const DB_NAME = 'cw-team-cache'
const STORE_NAME = 'snapshots'
const DB_VERSION = 1

function openDb() {
  if (!globalThis.indexedDB) return Promise.resolve(null)
  return new Promise((resolve, reject) => {
    const request = globalThis.indexedDB.open(DB_NAME, DB_VERSION)
    request.onupgradeneeded = () => {
      const db = request.result
      if (!db.objectStoreNames.contains(STORE_NAME)) {
        db.createObjectStore(STORE_NAME, { keyPath: 'key' })
      }
    }
    request.onsuccess = () => resolve(request.result)
    request.onerror = () => reject(request.error)
  })
}

function snapshotKey(userId, libraryId, type) {
  return `${userId}:${libraryId}:${type}`
}

export async function writeSnapshot(userId, libraryId, type, data) {
  if (!userId || !libraryId) return false
  let db = null
  try {
    db = await openDb()
    if (!db) return false
    await new Promise((resolve, reject) => {
      const tx = db.transaction(STORE_NAME, 'readwrite')
      tx.objectStore(STORE_NAME).put({
        key: snapshotKey(userId, libraryId, type),
        userId,
        libraryId,
        type,
        data,
        updatedAt: new Date().toISOString()
      })
      tx.oncomplete = resolve
      tx.onerror = () => reject(tx.error)
      tx.onabort = () => reject(tx.error)
    })
    return true
  } catch {
    return false
  } finally {
    db?.close()
  }
}

export async function readSnapshot(userId, libraryId, type) {
  if (!userId || !libraryId) return null
  let db = null
  try {
    db = await openDb()
    if (!db) return null
    return await new Promise((resolve, reject) => {
      const request = db
        .transaction(STORE_NAME, 'readonly')
        .objectStore(STORE_NAME)
        .get(snapshotKey(userId, libraryId, type))
      request.onsuccess = () => resolve(request.result || null)
      request.onerror = () => reject(request.error)
    })
  } catch {
    return null
  } finally {
    db?.close()
  }
}

async function clearMatching(predicate) {
  let db = null
  try {
    db = await openDb()
    if (!db) return false
    await new Promise((resolve, reject) => {
      const tx = db.transaction(STORE_NAME, 'readwrite')
      const store = tx.objectStore(STORE_NAME)
      const request = store.openCursor()
      request.onsuccess = () => {
        const cursor = request.result
        if (!cursor) return
        if (predicate(cursor.value)) cursor.delete()
        cursor.continue()
      }
      request.onerror = () => reject(request.error)
      tx.oncomplete = resolve
      tx.onerror = () => reject(tx.error)
      tx.onabort = () => reject(tx.error)
    })
    return true
  } catch {
    return false
  } finally {
    db?.close()
  }
}

export function clearAccountSnapshots(userId) {
  return clearMatching((row) => String(row.userId) === String(userId))
}

export function clearLibrarySnapshots(userId, libraryId) {
  return clearMatching(
    (row) =>
      String(row.userId) === String(userId) &&
      String(row.libraryId) === String(libraryId)
  )
}
