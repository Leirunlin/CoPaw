/**
 * RFC-6901 JSON Pointer ops — the subset A2UI's `updateDataModel` uses.
 * Mirrors the backend `qwenpaw.agents.genui.state` helpers so client and
 * server fold patches identically.
 */

function unescape(token: string): string {
  return token.replace(/~1/g, "/").replace(/~0/g, "~");
}

export function splitPointer(path: string): string[] {
  if (path === "" || path === "/") return [];
  if (!path.startsWith("/")) {
    throw new Error(`JSON pointer must start with '/': ${path}`);
  }
  return path
    .replace(/^\//, "")
    .split("/")
    .map(unescape);
}

type Json = unknown;

function descend(container: Json, token: string, create: boolean): Json {
  if (Array.isArray(container)) {
    const idx = token === "-" ? container.length : Number(token);
    if (create) {
      while (container.length <= idx) container.push({});
    }
    return container[idx];
  }
  if (container && typeof container === "object") {
    const obj = container as Record<string, Json>;
    if (create && !(token in obj)) obj[token] = {};
    return obj[token];
  }
  throw new Error(`cannot descend into ${typeof container} at ${token}`);
}

export function pointerUpsert(doc: Json, path: string, value: Json): Json {
  const tokens = splitPointer(path);
  if (tokens.length === 0) return value;
  const root = doc == null ? {} : doc;
  let parent: Json = root;
  for (const tok of tokens.slice(0, -1)) {
    parent = descend(parent, tok, true);
  }
  const last = tokens[tokens.length - 1];
  if (Array.isArray(parent)) {
    const idx = last === "-" ? parent.length : Number(last);
    while (parent.length <= idx) parent.push(null);
    parent[idx] = value;
  } else if (parent && typeof parent === "object") {
    (parent as Record<string, Json>)[last] = value;
  } else {
    throw new Error(`cannot set ${last} on ${typeof parent}`);
  }
  return root;
}

export function pointerDelete(doc: Json, path: string): Json {
  const tokens = splitPointer(path);
  if (tokens.length === 0) return {};
  let parent: Json = doc;
  try {
    for (const tok of tokens.slice(0, -1)) {
      parent = descend(parent, tok, false);
    }
    const last = tokens[tokens.length - 1];
    if (Array.isArray(parent)) {
      parent.splice(Number(last), 1);
    } else if (parent && typeof parent === "object") {
      delete (parent as Record<string, Json>)[last];
    }
  } catch {
    // deleting an absent path is a no-op
  }
  return doc;
}

export function pointerGet(doc: Json, path: string, fallback?: Json): Json {
  try {
    let cur: Json = doc;
    for (const tok of splitPointer(path)) {
      cur = descend(cur, tok, false);
    }
    return cur === undefined ? fallback : cur;
  } catch {
    return fallback;
  }
}
