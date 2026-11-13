// Installed into transport/internet in an explicitly selected Xray source tree.
// The original dialer is unchanged; emit only after its winning socket returns.
package internet

import (
	"context"
	"encoding/json"
	"fmt"
	"os"
	"strconv"
	"sync/atomic"
	"time"

	"github.com/xtls/xray-core/common/log"
	"github.com/xtls/xray-core/common/net"
	"github.com/xtls/xray-core/common/session"
)

var marzbanObserverSequence atomic.Uint64
var marzbanObserverEnabled = os.Getenv("MARZBAN_CONNECTION_OBSERVER") != "0"

func init() {
	for _, arg := range os.Args[1:] {
		if arg == "run" && marzbanObserverEnabled {
			fmt.Fprintln(os.Stdout, `MZCONN {"version":1,"event":"ready"}`)
			break
		}
	}
}

func DialSystem(ctx context.Context, dest net.Destination, sockopt *SocketConfig) (net.Conn, error) {
	conn, err := marzbanOriginalDialSystem(ctx, dest, sockopt)
	if err != nil || conn == nil || !marzbanObserverEnabled {
		return conn, err
	}
	inbound := session.InboundFromContext(ctx)
	if inbound == nil || inbound.User == nil || inbound.User.Email == "" {
		return conn, err
	}
	// A virtual pipe from dialerProxy has no numeric remote endpoint. Its actual
	// transport emits a separate event with the original authenticated context.
	remote := conn.RemoteAddr()
	local := conn.LocalAddr()
	if remote == nil || local == nil {
		return conn, err
	}
	var outbound string
	target := dest.String()
	outbounds := session.OutboundsFromContext(ctx)
	if len(outbounds) > 0 {
		outbound = outbounds[len(outbounds)-1].Tag
		if outbounds[0].Target.IsValid() {
			target = outbounds[0].Target.String()
		}
	}
	if access := log.AccessMessageFromContext(ctx); access != nil {
		target = fmt.Sprint(access.To)
	}
	now := time.Now().UTC()
	data, marshalErr := json.Marshal(map[string]interface{}{
		"version": 1, "event": "dial",
		"id":        strconv.FormatInt(now.UnixNano(), 10) + "-" + strconv.FormatUint(marzbanObserverSequence.Add(1), 10),
		"timestamp": now.Format(time.RFC3339Nano), "user": inbound.User.Email,
		"source": inbound.Source.String(), "target": target,
		"network": dest.Network.String(), "inbound": inbound.Tag,
		"outbound": outbound, "local": local.String(), "remote": remote.String(),
	})
	if marshalErr == nil {
		// One bounded record, no accounts, passwords, UUIDs or routing configuration.
		fmt.Fprintf(os.Stdout, "MZCONN %s\n", data)
	}
	return conn, err
}
