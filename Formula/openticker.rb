# Homebrew formula for OpenTicker.
#
#   brew install bin01/tap/openticker && openticker
#
# It installs a small `openticker` command. The first time you run it, it sets OpenTicker up in ~/.openticker with
# the same installer as the one-line install (the code, a private Python, the background server, the Mac app),
# and from then on hands every command to the CLI there. `openticker update` updates OpenTicker itself and keeps
# your changes; `brew upgrade` only updates the launcher.
class Openticker < Formula
  desc "Stock market dashboard for your Mac, with your own AI agent built in"
  homepage "https://github.com/bin01/openticker"
  url "https://github.com/bin01/openticker/archive/8c6354120a5213091497598bc38bc177a4242c54.tar.gz"
  version "0.1.0"
  sha256 "f6930e0f1bf40c076a3b8dd4c5f5264c07b4543017e8ec72440f65e5f7cce1db"
  license "Apache-2.0"
  head "https://github.com/bin01/openticker.git", branch: "main"

  depends_on "uv"

  def install
    libexec.install "install.sh"
    inreplace "packaging/homebrew/launcher.sh", "@@LIBEXEC@@", opt_libexec.to_s
    bin.install "packaging/homebrew/launcher.sh" => "openticker"
  end

  def caveats
    <<~EOS
      Finish setting up OpenTicker (about a minute the first time):
        openticker

      Add --lan to let your phone connect over Wi-Fi:
        openticker setup --lan

      OpenTicker keeps its code in ~/.openticker and your data in
      ~/Library/Application Support/OpenTicker. Update it with `openticker update`.
    EOS
  end

  test do
    assert_match opt_libexec.to_s, (bin/"openticker").read
    assert_predicate libexec/"install.sh", :exist?
  end
end
