try {
    const wsURI = 'ws://localhost:8080';
    const ws = new WebSocket(wsURI);

    const messages = document.getElementById('messages');
    const message = document.getElementById('message');

    // ws.addEventListener('open', function (event) {
    //     ws.send('Hello Server!');
    // });

    ws.addEventListener('message', function (event) {
        messages.innerHTML += `<li>${event.data}</li>`
    });

    ws.onerror = function (error) {
        console.error("Websocket error:", error);
        messages.innerHTML = `Error to handle ${wsURI}` 
    };

    document.addEventListener('click', (event) => {
        let selected = document.elementFromPoint(event.clientX, event.clientY);
        if (selected && selected.id != 'message') {
            message.style.left = event.clientX + "px";
            message.style.top = event.clientY + "px";
        }
    });

    message.addEventListener('keyup', (event) => {
        if (event.key === 'Enter') {
            try {
                ws.send(message.value)
            } catch (err) {
                alert(err);
            } finally {
                message.value = '';
            }
        }
    });
} catch (err) {
    messages.innerHTML = `Error on connect: ${err}` 
}