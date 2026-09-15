import { afterAll, afterEach, beforeAll, describe, expect, it, vi } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { setupServer } from "msw/node";
import type { ComponentType } from "react";

// Pin the API base BEFORE the component (and its api.ts import) is loaded.
process.env.NEXT_PUBLIC_API_URL = "http://api.test";
vi.stubGlobal("process", {
  ...process,
  env: { ...process.env, NEXT_PUBLIC_API_URL: "http://api.test" },
});

let received: unknown = null;
const server = setupServer(
  http.post("http://api.test/api/newsletter", async ({ request }) => {
    received = await request.json();
    return HttpResponse.json({ status: "subscribed" });
  }),
);

let NewsletterForm: ComponentType;

beforeAll(async () => {
  ({ NewsletterForm } = await import("./NewsletterForm"));
  server.listen({ onUnhandledRequest: "error" });
});
afterEach(() => {
  server.resetHandlers();
  received = null;
});
afterAll(() => server.close());

describe("NewsletterForm", () => {
  it("rejects an invalid email without calling the API", async () => {
    const user = userEvent.setup();
    render(<NewsletterForm />);
    await user.type(screen.getByLabelText("E-posta adresi"), "nope");
    await user.click(screen.getByRole("button", { name: "Abone ol" }));
    expect(await screen.findByText("Geçerli bir e-posta adresi girin.")).toBeInTheDocument();
    expect(received).toBeNull();
  });

  it("requires the consent checkbox", async () => {
    const user = userEvent.setup();
    render(<NewsletterForm />);
    await user.type(screen.getByLabelText("E-posta adresi"), "ada@example.com");
    await user.click(screen.getByRole("button", { name: "Abone ol" }));
    expect(
      await screen.findByText("Abone olmak için onay kutusunu işaretleyin."),
    ).toBeInTheDocument();
    expect(received).toBeNull();
  });

  it("subscribes with consent and confirms", async () => {
    const user = userEvent.setup();
    render(<NewsletterForm />);
    await user.type(screen.getByLabelText("E-posta adresi"), "ada@example.com");
    await user.click(screen.getByRole("checkbox"));
    await user.click(screen.getByRole("button", { name: "Abone ol" }));
    await waitFor(() => expect(screen.getByRole("status")).toHaveTextContent("Abone oldunuz."));
    expect(received).toEqual({ email: "ada@example.com", consent: true, website: "" });
  });
});
