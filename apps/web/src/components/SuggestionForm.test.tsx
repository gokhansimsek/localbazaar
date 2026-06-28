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

const provinces = [
  { slug: "istanbul", name: "İstanbul", plate_code: 34 },
  { slug: "izmir", name: "İzmir", plate_code: 35 },
];

const server = setupServer(
  http.post("http://api.test/api/suggestions", () =>
    HttpResponse.json({ id: 1, status: "pending" }),
  ),
);

// Loaded dynamically so the api.test base URL is in place first.
let SuggestionForm: ComponentType<{
  provinces: typeof provinces;
  mode: "add" | "update";
  onModeChange: (m: "add" | "update") => void;
  draftPin: { lat: number; lng: number } | null;
  selectedMarket: null;
  onClose: () => void;
}>;

beforeAll(async () => {
  ({ SuggestionForm } = await import("./SuggestionForm"));
  server.listen({ onUnhandledRequest: "error" });
});
afterEach(() => server.resetHandlers());
afterAll(() => server.close());

describe("SuggestionForm", () => {
  it("renders identity and explanation fields", () => {
    render(
      <SuggestionForm
        provinces={provinces}
        mode="add"
        onModeChange={() => {}}
        draftPin={null}
        selectedMarket={null}
        onClose={() => {}}
      />,
    );
    expect(screen.getByText("Ad")).toBeInTheDocument();
    expect(screen.getByText("Soyad")).toBeInTheDocument();
    expect(screen.getByText("E-posta")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Öneriyi gönder" })).toBeInTheDocument();
  });

  it("blocks submit and shows an error when required fields are missing", async () => {
    const user = userEvent.setup();
    render(
      <SuggestionForm
        provinces={provinces}
        mode="add"
        onModeChange={() => {}}
        draftPin={null}
        selectedMarket={null}
        onClose={() => {}}
      />,
    );
    await user.click(screen.getByRole("button", { name: "Öneriyi gönder" }));
    expect(await screen.findByText("Ad ve soyad gerekli.")).toBeInTheDocument();
  });

  it("submits an add suggestion and confirms success", async () => {
    const user = userEvent.setup();
    render(
      <SuggestionForm
        provinces={provinces}
        mode="add"
        onModeChange={() => {}}
        draftPin={{ lat: 41, lng: 29 }}
        selectedMarket={null}
        onClose={() => {}}
      />,
    );
    await user.type(screen.getByLabelText("Ad"), "Ada");
    await user.type(screen.getByLabelText("Soyad"), "Yılmaz");
    await user.type(screen.getByLabelText("E-posta"), "ada@example.com");
    await user.type(screen.getByLabelText("Yer adı"), "Yeni Pazar");
    await user.type(screen.getByLabelText("Açıklama"), "Burada büyük bir pazar var.");
    await user.click(screen.getByRole("button", { name: "Öneriyi gönder" }));
    await waitFor(() => expect(screen.getByText(/Teşekkürler/i)).toBeInTheDocument());
  });
});
