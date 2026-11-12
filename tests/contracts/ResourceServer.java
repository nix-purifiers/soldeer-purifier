import com.sun.net.httpserver.HttpServer;
import java.net.*;
import java.nio.file.*;
import java.security.MessageDigest;
import java.util.*;

public class ResourceServer {
  public static void main(String[] args) throws Exception {
    Path jar = Path.of(args[0]).toRealPath();
    var loader = new URLClassLoader(new URL[]{jar.toUri().toURL()}, null);
    Map<String,String> hashes = new HashMap<>();
    for (String line : Files.readAllLines(Path.of(args[2]))) {
      String[] fields = line.split("\t"); hashes.put(fields[0], fields[1]);
    }
    var server = HttpServer.create(new InetSocketAddress("127.0.0.1", 0), 0);
    server.createContext("/", exchange -> {
      String name = exchange.getRequestURI().getPath().substring(1);
      if (!hashes.containsKey(name)) {
        exchange.sendResponseHeaders(404, -1); exchange.close(); return;
      }
      URL resource = loader.getResource(args[1] + name);
      try {
        if (resource == null || !resource.getProtocol().equals("jar")) throw new AssertionError("JAR resource origin");
        var connection = (JarURLConnection)resource.openConnection();
        if (!Path.of(connection.getJarFileURL().toURI()).toRealPath().equals(jar)) throw new AssertionError("wrong JAR");
        byte[] bytes;
        try (var stream = connection.getInputStream()) { bytes = stream.readAllBytes(); }
        String digest = HexFormat.of().formatHex(MessageDigest.getInstance("SHA-256").digest(bytes));
        if (!digest.equals(hashes.get(name))) throw new AssertionError("resource bytes");
        String mime = name.endsWith(".json") ? "application/json" : name.endsWith(".wasm") ? "application/wasm" : name.endsWith(".css") ? "text/css" : name.endsWith(".html") ? "text/html" : "text/javascript";
        exchange.getResponseHeaders().set("Content-Type", mime);
        exchange.sendResponseHeaders(200, bytes.length);
        try (var body = exchange.getResponseBody()) { body.write(bytes); }
      } catch (Exception error) { throw new RuntimeException(error); }
      finally { exchange.close(); }
    });
    Runtime.getRuntime().addShutdownHook(new Thread(() -> { server.stop(0); try { loader.close(); } catch (Exception ignored) {} }));
    server.start(); System.out.println(server.getAddress().getPort()); System.out.flush();
  }
}
