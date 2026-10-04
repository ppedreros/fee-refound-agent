import { copy } from "./copy/en";
import { Queue } from "./features/queue/Queue";
import { useUrlState } from "./lib/useUrlState";

export default function App() {
  const [{ view, caseId }, navigate] = useUrlState();

  return (
    <div className="flex min-h-screen flex-col">
      <header className="flex h-14 items-center border-b border-grey-200 bg-white px-6">
        <h1 className="font-serif text-lg">{copy.app.title}</h1>
      </header>
      <div className="flex flex-1 flex-col lg:flex-row">
        <nav
          aria-label={copy.queue.label}
          className="border-b border-grey-200 lg:w-80 lg:shrink-0 lg:border-r lg:border-b-0"
        >
          <Queue
            view={view}
            selectedId={caseId}
            onViewChange={(next) => {
              navigate({ view: next, caseId: null });
            }}
            onSelect={(id) => {
              navigate({ view, caseId: id });
            }}
          />
        </nav>
        <main
          aria-label={copy.case.label}
          className="flex flex-1 items-center justify-center bg-white p-8"
        >
          {caseId === null && <p className="text-grey-600">{copy.case.empty}</p>}
        </main>
      </div>
    </div>
  );
}
