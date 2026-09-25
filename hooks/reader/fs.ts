/**
 * The file access the reader needs, narrow enough that `$.fs` and a test's
 * in-memory tree both satisfy it. Paths are relative to the session's
 * working directory or absolute, as `$.fs` takes them.
 */
export type ReaderFs = {
  read: (path: string) => Promise<string>
  list: (path: string) => Promise<{ name: string; kind: 'file' | 'dir' | 'other'; size: number }[]>
  exists: (path: string) => Promise<boolean>
  stat: (path: string) => Promise<{ kind: 'file' | 'dir' | 'other'; size: number; mtimeMs: number }>
}

/** `read`, or null when the file is missing, unreadable or over the size cap. */
export async function readOrNull(fs: ReaderFs, path: string): Promise<string | null> {
  try {
    // `exists` never rejects; asking first keeps a missing optional file out of the error log.
    if (!(await fs.exists(path))) {
      return null
    }

    return await fs.read(path)
  } catch {
    return null
  }
}

/** `list`, or an empty list when the directory is missing. */
export async function listOrEmpty(
  fs: ReaderFs,
  path: string,
): Promise<{ name: string; kind: 'file' | 'dir' | 'other'; size: number }[]> {
  try {
    if (!(await fs.exists(path))) {
      return []
    }

    return await fs.list(path)
  } catch {
    return []
  }
}

/** `stat`'s mtime, or null when the path is missing. */
export async function mtimeOrNull(fs: ReaderFs, path: string): Promise<number | null> {
  try {
    if (!(await fs.exists(path))) {
      return null
    }

    return (await fs.stat(path)).mtimeMs
  } catch {
    return null
  }
}
