/** No year on purpose: an image running in an air-gapped site is not rebuilt in January. */
export function AppFooter() {
  return (
    <footer className="mx-auto w-full max-w-[1800px] px-4 pb-6 pt-2 text-center text-[12.5px] text-subtle sm:px-8">
      © Itay Herzberg & Oshri Belai & Roi Blum
    </footer>
  );
}
