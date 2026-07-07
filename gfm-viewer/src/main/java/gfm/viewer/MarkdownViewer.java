package gfm.viewer;

import java.io.IOException;
import java.nio.file.*;
import java.util.List;

import gfm.parser.*;
import javafx.application.Application;
import javafx.concurrent.Task;
import javafx.scene.Scene;
import javafx.scene.control.*;
import javafx.scene.layout.*;
import javafx.scene.web.WebView;
import javafx.stage.FileChooser;
import javafx.stage.Stage;

public class MarkdownViewer extends Application {
    private WebView webView;
    private Path currentFile;
    private Stage stage;
    private WatchService watcher;
    private Thread watcherThread;

    private static final String CSS = """
        <style>
          body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
                 max-width: 800px; margin: 0 auto; padding: 20px;
                 line-height: 1.6; color: #1f2328; }
          pre { background: #f6f8fa; padding: 16px; border-radius: 6px; overflow-x: auto; }
          code { background: #f6f8fa; padding: 2px 6px; border-radius: 4px; font-size: 85%; }
          pre code { background: none; padding: 0; }
          table { border-collapse: collapse; width: 100%; }
          th, td { border: 1px solid #d0d7de; padding: 8px 12px; text-align: left; }
          th { background: #f6f8fa; font-weight: 600; }
          blockquote { border-left: 4px solid #d0d7de; margin: 0; padding: 0 16px; color: #656d76; }
          img { max-width: 100%; }
          h1 { border-bottom: 1px solid #d0d7de; padding-bottom: 8px; }
          h2 { border-bottom: 1px solid #d0d7de; padding-bottom: 6px; }
          a { color: #0969da; text-decoration: none; }
          a:hover { text-decoration: underline; }
          hr { border: none; border-top: 1px solid #d0d7de; }
          ul { padding-left: 24px; }
          ol { padding-left: 24px; }
          input[type=checkbox] { margin-right: 8px; }
        </style>
        """;

    @Override
    public void start(Stage st) {
        this.stage = st;
        webView = new WebView();
        VBox root = new VBox();
        MenuBar menuBar = createMenuBar();
        root.getChildren().addAll(menuBar, webView);
        VBox.setVgrow(webView, Priority.ALWAYS);

        Scene scene = new Scene(root, 900, 700);
        stage.setTitle("GFM Viewer");
        stage.setScene(scene);

        List<String> args = getParameters().getRaw();
        if (!args.isEmpty()) {
            openFile(Paths.get(args.get(0)));
        }

        stage.show();
    }

    private MenuBar createMenuBar() {
        MenuBar mb = new MenuBar();
        Menu fileMenu = new Menu("File");

        MenuItem open = new MenuItem("Open...");
        open.setOnAction(e -> {
            FileChooser fc = new FileChooser();
            fc.getExtensionFilters().add(
                new FileChooser.ExtensionFilter("Markdown", "*.md", "*.markdown", "*.mdown", "*.mkdn"));
            java.io.File f = fc.showOpenDialog(stage);
            if (f != null) openFile(f.toPath());
        });

        MenuItem reload = new MenuItem("Reload");
        reload.setOnAction(e -> { if (currentFile != null) renderFile(currentFile); });

        MenuItem exit = new MenuItem("Exit");
        exit.setOnAction(e -> {
            stopWatcher();
            javafx.application.Platform.exit();
        });

        fileMenu.getItems().addAll(open, reload, new SeparatorMenuItem(), exit);
        mb.getMenus().add(fileMenu);

        Menu viewMenu = new Menu("View");
        MenuItem source = new MenuItem("View Source");
        source.setOnAction(e -> showSource());
        viewMenu.getItems().add(source);
        mb.getMenus().add(viewMenu);

        return mb;
    }

    private void openFile(Path path) {
        currentFile = path.toAbsolutePath().normalize();
        renderFile(currentFile);
        stage.setTitle("GFM Viewer - " + currentFile.getFileName());
        startWatcher(currentFile);
    }

    private void renderFile(Path path) {
        try {
            String md = Files.readString(path);
            Task<String> renderTask = new Task<>() {
                @Override
                protected String call() {
                    BlockParser bp = new BlockParser();
                    AstNode doc = bp.parse(md);
                    HtmlRenderer hr = new HtmlRenderer();
                    String html = hr.render(doc);
                    return "<!DOCTYPE html><html><head><meta charset=\"utf-8\">" + CSS + "</head><body>"
                           + html + "</body></html>";
                }
            };
            renderTask.setOnSucceeded(e -> webView.getEngine().loadContent(renderTask.getValue()));
            renderTask.setOnFailed(e -> {
                String msg = renderTask.getException().getMessage();
                webView.getEngine().loadContent(
                    "<html><body><h2>Parse Error</h2><pre>" +
                    (msg != null ? msg : "Unknown error") + "</pre></body></html>");
            });
            new Thread(renderTask).start();
        } catch (IOException e) {
            webView.getEngine().loadContent(
                "<html><body><h2>Error</h2><p>" + e.getMessage() + "</p></body></html>");
        }
    }

    private void showSource() {
        if (currentFile != null) {
            try {
                String md = Files.readString(currentFile);
                Stage srcStage = new Stage();
                TextArea ta = new TextArea(md);
                ta.setEditable(false);
                ta.setFont(javafx.scene.text.Font.font("Monaco", 12));
                Scene s = new Scene(ta, 600, 400);
                srcStage.setTitle("Source: " + currentFile.getFileName());
                srcStage.setScene(s);
                srcStage.show();
            } catch (IOException e) {
                // ignore
            }
        }
    }

    private void startWatcher(Path path) {
        stopWatcher();
        try {
            watcher = FileSystems.getDefault().newWatchService();
            path.getParent().register(watcher, StandardWatchEventKinds.ENTRY_MODIFY);
            watcherThread = new Thread(() -> {
                try {
                    while (true) {
                        WatchKey key = watcher.take();
                        for (WatchEvent<?> event : key.pollEvents()) {
                            Path changed = (Path) event.context();
                            if (changed.equals(path.getFileName())) {
                                javafx.application.Platform.runLater(() -> renderFile(currentFile));
                            }
                        }
                        key.reset();
                    }
                } catch (InterruptedException | ClosedWatchServiceException e) {
                    Thread.currentThread().interrupt();
                }
            }, "file-watcher");
            watcherThread.setDaemon(true);
            watcherThread.start();
        } catch (IOException e) {
            // File watching not available
        }
    }

    private void stopWatcher() {
        if (watcher != null) {
            try {
                watcher.close();
            } catch (IOException e) { }
            watcher = null;
        }
        if (watcherThread != null) {
            watcherThread.interrupt();
            watcherThread = null;
        }
    }

    public static void main(String[] args) {
        launch(args);
    }
}
