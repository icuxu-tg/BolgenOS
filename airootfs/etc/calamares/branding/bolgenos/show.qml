import QtQuick 2.0;
import calamares.slideshow 1.0;

Presentation {
    id: presentation
    Slide {
        Text { anchors.centerIn: parent; text: "Добро пожаловать в BolgenOS"; color: "#1a2a4a"; font.pixelSize: 28 }
    }
    Slide {
        Text { anchors.centerIn: parent; text: "MATE, Calamares и нужные приложения уже готовы"; color: "#1a2a4a"; font.pixelSize: 24 }
    }
}
