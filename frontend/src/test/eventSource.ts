// A stand-in for the browser's EventSource, so tests can send a check's events one by one.
export class FakeEventSource {
  static instances: FakeEventSource[] = [];

  readonly url: string;
  onmessage: ((message: MessageEvent<string>) => void) | null = null;
  closed = false;

  constructor(url: string) {
    this.url = url;
    FakeEventSource.instances.push(this);
  }

  /** Sends one event from the server. */
  send(event: object): void {
    this.onmessage?.(new MessageEvent("message", { data: JSON.stringify(event) }));
  }

  close(): void {
    this.closed = true;
  }

  static latest(): FakeEventSource {
    const source = FakeEventSource.instances.at(-1);
    if (source === undefined) throw new Error("No EventSource was opened");
    return source;
  }
}
