import { StringDecoder } from "node:string_decoder";

export class JsonlDecoder {
  #decoder = new StringDecoder("utf8");
  #buffer = "";

  push(chunk) {
    this.#buffer += typeof chunk === "string" ? chunk : this.#decoder.write(chunk);
    return this.#drain(false);
  }

  end(chunk) {
    if (chunk !== undefined) this.#buffer += typeof chunk === "string" ? chunk : this.#decoder.write(chunk);
    this.#buffer += this.#decoder.end();
    return this.#drain(true);
  }

  #drain(final) {
    const values = [];
    while (true) {
      const newline = this.#buffer.indexOf("\n");
      if (newline === -1) break;
      let line = this.#buffer.slice(0, newline);
      this.#buffer = this.#buffer.slice(newline + 1);
      if (line.endsWith("\r")) line = line.slice(0, -1);
      if (line.length > 0) values.push(JSON.parse(line));
    }
    if (final && this.#buffer.length > 0) {
      let line = this.#buffer;
      this.#buffer = "";
      if (line.endsWith("\r")) line = line.slice(0, -1);
      if (line.length > 0) values.push(JSON.parse(line));
    }
    return values;
  }
}
