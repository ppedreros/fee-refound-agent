import { copy } from "./copy/en";
import { CasePane } from "./features/case/CasePane";
import { Queue } from "./features/queue/Queue";
import { useUrlState } from "./lib/useUrlState";

export default function App() {
  const [{ view, caseId }, navigate] = useUrlState();

  return (
    <div className="flex min-h-screen flex-col">
      <header className="flex h-14 items-center border-b border-grey-200 bg-white px-6">
        <h1 className="font-serif text-lg">{copy.app.title}</h1>
      </header>
      {/* Two panes from 1024 px; below that, one pane: the queue, or the case it opened. */}
      <div className="flex flex-1 flex-col lg:flex-row">
        <nav
          aria-label={copy.queue.label}
          className={`border-b border-grey-200 lg:block lg:w-80 lg:shrink-0 lg:border-r lg:border-b-0 ${
            caseId === null ? "" : "hidden"
          }`}
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
          className={`min-w-0 flex-1 bg-white ${
            caseId === null ? "hidden p-8 lg:flex lg:items-center lg:justify-center" : ""
          }`}
        >
          {caseId === null ? (
            <p className="text-grey-600">{copy.case.empty}</p>
          ) : (
            <CasePane
              key={caseId}
              caseId={caseId}
              onBack={() => {
                navigate({ view, caseId: null });
              }}
              onNext={(id) => {
                navigate({ view: "open", caseId: id });
              }}
            />
          )}
        </main>
      </div>
    </div>
  );
}
