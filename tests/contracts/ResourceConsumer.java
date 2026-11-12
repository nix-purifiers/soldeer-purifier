import java.net.URLClassLoader;
import java.nio.file.Files;
import java.nio.file.Path;
import java.security.MessageDigest;
import java.util.HexFormat;

public class ResourceConsumer {
  public static void main(String[] args) throws Exception {
    Path jar = Path.of(args[0]).toRealPath();
    String prefix = args[2];
    int count = 0;
    try (var loader = new URLClassLoader(new java.net.URL[] {jar.toUri().toURL()}, null)) {
      for (String line : Files.readAllLines(Path.of(args[1]))) {
        String[] row = line.split("\t");
        String name = prefix + row[0];
        var origin = loader.getResource(name);
        if (origin == null || !(origin.openConnection() instanceof java.net.JarURLConnection connection)
            || !Path.of(connection.getJarFileURL().toURI()).toRealPath().equals(jar)
            || !connection.getEntryName().equals(name)) {
          throw new AssertionError("resource origin differs: " + name + " -> " + origin);
        }
        try (var stream = loader.getResourceAsStream(name)) {
          String digest = HexFormat.of().formatHex(MessageDigest.getInstance("SHA-256").digest(stream.readAllBytes()));
          if (!digest.equals(row[1])) throw new AssertionError("resource bytes differ: " + name);
        }
        count++;
      }
      if (loader.getResource(prefix + "private.txt") != null) {
        throw new AssertionError("private sibling leaked");
      }
    }
    System.out.println("Java loaded " + count + " exact contract resources from " + jar);
  }
}
