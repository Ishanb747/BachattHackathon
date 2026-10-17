export class AuthError extends Error {
  constructor(msg = "Not signed in") { super(msg); this.name = "AuthError"; this.status = 401; }
}
